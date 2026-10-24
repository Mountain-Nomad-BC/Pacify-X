'use strict';

const { EFFECT_ORDER } = require('./taskStore');
const { PxToolRequest, PxToolResult, parse } = require('./contracts');
const { nowIso } = require('./ids');
const { validateExecutionContextForRun } = require('./executionContext');

class ToolBroker {
  constructor(options = {}) { this.tools = new Map(); this.loading = new Map(); this.approvalProvider = options.approvalProvider || null; this.eventBus = options.eventBus || null; }

  register(tool) {
    if (!tool?.toolId || !EFFECT_ORDER.includes(tool.effectClass) || typeof tool.execute !== 'function') throw new Error('tool-registration-invalid');
    if (this.tools.has(tool.toolId)) throw new Error(`tool-already-registered:${tool.toolId}`);
    this.tools.set(tool.toolId, { ...tool }); return { dispose: () => this.tools.delete(tool.toolId) };
  }

  registerLazy(metadata, loader) {
    if (!metadata?.toolId || !EFFECT_ORDER.includes(metadata.effectClass) || typeof loader !== 'function') throw new Error('lazy-tool-registration-invalid');
    if (this.tools.has(metadata.toolId)) throw new Error(`tool-already-registered:${metadata.toolId}`);
    const entry = { toolId: metadata.toolId, effectClass: metadata.effectClass,
      requireApproval: metadata.requireApproval === true, description: String(metadata.description || '').slice(0, 1000),
      serverId: metadata.serverId || null, revision: metadata.revision || null, loader };
    this.tools.set(entry.toolId, entry);
    return { dispose: () => { if (this.tools.get(entry.toolId) === entry) this.tools.delete(entry.toolId); } };
  }

  // Discovery carries descriptions, never every server's schemas or implementation.
  list() { return [...this.tools.values()].map(tool => ({ toolId: tool.toolId, effectClass: tool.effectClass,
    requireApproval: tool.requireApproval === true, description: String(tool.description || '').slice(0, 1000),
    serverId: tool.serverId || null, revision: tool.revision || null, loaded: typeof tool.execute === 'function' })); }

  async _load(entry) {
    if (typeof entry.execute === 'function') return entry;
    if (!this.loading.has(entry)) {
      const pending = Promise.resolve().then(() => entry.loader()).then(loaded => {
        if (this.tools.get(entry.toolId) !== entry) throw new Error('tool-registration-changed-during-load');
        if (!loaded || loaded.toolId !== entry.toolId || loaded.effectClass !== entry.effectClass ||
            (loaded.requireApproval === true) !== entry.requireApproval ||
            typeof loaded.execute !== 'function' || typeof loaded.validateArguments !== 'function' ||
            !loaded.inputSchema || Buffer.byteLength(JSON.stringify(loaded.inputSchema), 'utf8') > 65536) {
          throw new Error('lazy-tool-owner-or-contract-mismatch');
        }
        entry.execute = loaded.execute; entry.inputSchema = loaded.inputSchema; entry.validateArguments = loaded.validateArguments;
        return entry;
      }).finally(() => this.loading.delete(entry));
      this.loading.set(entry, pending);
    }
    return this.loading.get(entry);
  }

  async describe(toolIds) {
    if (!Array.isArray(toolIds) || toolIds.length > 8 || new Set(toolIds).size !== toolIds.length) throw new Error('tool-schema-selection-budget-exceeded');
    const selected = [];
    for (const id of toolIds) {
      const entry = this.tools.get(id); if (!entry) throw new Error(`unknown-tool:${id}`);
      const loaded = await this._load(entry);
      selected.push({ toolId: loaded.toolId, effectClass: loaded.effectClass,
        description: loaded.description || '', inputSchema: loaded.inputSchema || null });
    }
    return selected;
  }

  async execute(input, task, executionContext) {
    const request = parse(PxToolRequest, input, 'tool-request');
    if (executionContext == null) throw new Error('execution-context-required');
    validateExecutionContextForRun(executionContext, request.runId);
    let tool = this.tools.get(request.toolId);
    if (!tool) return this._result(request, 'blocked', 'Unknown tool.', null, []);
    if (request.taskId !== task.taskId) return this._result(request, 'blocked', 'Tool request task owner mismatch.', null, []);
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
      tool = await this._load(tool);
      if (tool.validateArguments && await tool.validateArguments(request.arguments) !== true) throw new Error('tool-arguments-rejected-by-native-contract');
      const value = await tool.execute({ request, task, executionContext });
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
