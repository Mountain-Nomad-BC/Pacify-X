'use strict';

const path = require('node:path');
const crypto = require('node:crypto');
const fs = require('node:fs');
const { readScopedEditor } = require('./vscodeTools');
const { MESSAGE_VERSION, ASSET_PROTOCOL, validateInbound, validateOutbound } = require('./agentConsoleMessages');
const { buildAgentConsoleProjection, redactEventPayload } = require('./agentConsoleProjection');

class AgentConsoleViewProvider {
  constructor(vscode, context, options) { this.vscode = vscode; this.context = context; this.harness = options.harness; this.workspaceRootProvider = options.workspaceRootProvider; this.openControlPlane = options.openControlPlane; this.onDiagnostic = options.onDiagnostic || (() => {}); this.view = null; this.disposables = [];
    this.disposables.push(this.harness.eventBus.subscribe(event => Promise.all([this._post({ schemaVersion: MESSAGE_VERSION, type: 'event', event: { ...event, payload: redactEventPayload(event) } }), this.publish()]))); }

  resolveWebviewView(view) {
    this.view = view; const webview = view.webview; webview.options = { enableScripts: true, localResourceRoots: [this.vscode.Uri.file(path.join(this.context.extensionPath, 'media'))] }; webview.html = this._html(webview);
    this.disposables.push(webview.onDidReceiveMessage(message => void this._handle(message)));
    void this.publish();
  }

  async _handle(raw) {
    let message; try { message = validateInbound(raw); } catch (error) { this.onDiagnostic(`agent-console-message-rejected:${error.message}`); return this._error('message-rejected', 'Agent Console message was rejected by the host contract.'); }
    try {
      if (message.type === 'ready' || message.type === 'refresh') return this.publish();
      if (message.type === 'openControlPlane') return this.openControlPlane?.();
      if (message.type === 'cancelRun') { await this.harness.cancelRun(message.runId); return this.publish(); }
      if (message.type === 'newTask') { this.harness.createTask({ goal: message.goal, mode: message.mode, maxEffectClass: message.maxEffectClass, ...this._defaults() }); return this.publish(); }
      if (message.type === 'sendTurn') {
        let taskId = message.taskId;
        if (!taskId) taskId = this.harness.createTask({ goal: message.message, mode: message.mode, maxEffectClass: message.maxEffectClass, ...this._defaults() }).taskId;
        else this.harness.taskStore.updateTask(taskId, { mode: message.mode, constraints: { maxEffectClass: message.maxEffectClass } });
        void this.harness.sendTurn({ taskId, runId: message.runId, message: message.message, workerId: message.workerId, explicitRefs: this._editorRefs() }).catch(error => this._error('run-failed', String(error?.message || error).slice(0, 900)));
        return this.publish();
      }
    } catch (error) { this.onDiagnostic(`agent-console-handler:${error?.stack || error}`); return this._error('host-action-failed', String(error?.message || error).slice(0, 900)); }
  }

  _defaults() { const s = this.harness.hostSettings?.() || {}; return { contextBudgetTokens: s.contextInjectionCapTokens || 12000, taskCostCeilingUsd: s.executionPolicy?.max_cost_per_task_usd ?? null, localFirst: s.executionPolicy?.local_first !== false, requireApprovalBeforeBillable: s.executionPolicy?.require_approval_before_billable_execution !== false }; }
  _editorRefs() {
    let selected;
    try { selected = readScopedEditor(this.vscode, this.workspaceRootProvider); }
    catch { return []; }
    if (!selected) return [];
    if (selected.selection) return [{ refId: 'active-selection', kind: 'editor-selection', label: `Selection: ${path.basename(selected.file)}`, source: selected.file, content: selected.selection, authority: 'active-editor' }];
    return [{ refId: 'active-file-ref', kind: 'editor-file', label: `Active file: ${path.basename(selected.file)}`, source: selected.file, content: null, authority: 'active-editor' }];
  }

  async publish() { return this._post({ schemaVersion: MESSAGE_VERSION, type: 'snapshot', assetProtocol: ASSET_PROTOCOL, state: buildAgentConsoleProjection(this.harness.project()) }); }
  async _error(code, detail) { return this._post({ schemaVersion: MESSAGE_VERSION, type: 'error', code, detail }); }
  async _post(message) { if (!this.view) return; let valid; try { valid = validateOutbound(message); } catch (error) { this.onDiagnostic(`agent-console-outbound-rejected:${error.message}`); return; } await this.view.webview.postMessage(valid); }

  _html(webview) {
    const media = name => webview.asWebviewUri(this.vscode.Uri.file(path.join(this.context.extensionPath, 'media', name))); const nonce = crypto.randomBytes(18).toString('base64');
    return `<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';"><link rel="stylesheet" href="${media('agent-console.css')}"><title>PX Agent Console</title></head><body><main id="app"></main><script nonce="${nonce}">window.__PX_AGENT_PROTOCOL__=${JSON.stringify({ message: MESSAGE_VERSION, asset: ASSET_PROTOCOL })};</script><script nonce="${nonce}" src="${media('agent-console.js')}"></script></body></html>`;
  }

  dispose() { for (const d of this.disposables.splice(0)) d?.dispose?.(); this.view = null; }
}

function withinProject(file, root) {
  if (!file || !root) return false;
  try {
    const physicalFile = fs.realpathSync.native(file);
    const physicalRoot = fs.realpathSync.native(root);
    if (!fs.statSync(physicalRoot).isDirectory() || !fs.statSync(physicalFile).isFile()) return false;
    const relative = path.relative(physicalRoot, physicalFile);
    return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
  } catch { return false; }
}

module.exports = { AgentConsoleViewProvider, withinProject };
