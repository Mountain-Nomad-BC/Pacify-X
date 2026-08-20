'use strict';

const path = require('path');
const crypto = require('crypto');
const { buildSidebarProjection } = require('./sidebarProjection');
const { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL, validateSidebarInbound, validateSidebarOutbound, describeSidebarInboundRejection } = require('./sidebarMessages');

const PREF_KEY = 'pacifyX.sidebar.ui/1.0';

function sidebarHtml(vscode, webview, extensionPath) {
  const media = name => webview.asWebviewUri(vscode.Uri.file(path.join(extensionPath, 'media', name)));
  const nonce = crypto.randomBytes(18).toString('base64');
  return `<!doctype html>
<html lang="en"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}'; img-src ${webview.cspSource} data:;">
  <link rel="stylesheet" href="${media('sidebar.css')}"><title>Pacify-X Live Operations</title>
</head><body>
  <main id="sidebar" aria-label="Pacify-X live operations console">
    <section id="header" data-component="header" aria-live="polite"></section>
    <div id="operational-scroll">
      <section id="connection" data-component="connection"></section>
      <section id="execution" data-component="execution"></section>
      <section id="waves" data-component="waves"></section>
      <section id="punch" data-component="punch"></section>
      <section id="agents" data-component="agents"></section>
      <section id="orchestrations" data-component="orchestrations"></section>
      <section id="recent" data-component="recent"></section>
      <section id="attention" data-component="attention"></section>
    </div>
    <section id="providers" data-component="providers" aria-label="Provider and billing activity"></section>
    <div id="contract-error" role="alert" hidden></div>
  </main>
  <script nonce="${nonce}" src="${media('sidebar.js')}"></script>
</body></html>`;
}

class SidebarViewProvider {
  constructor(vscode, context, callbacks = {}) {
    this.vscode = vscode;
    this.context = context;
    this.callbacks = callbacks;
    this.view = null;
    this.resolveCount = 0;
    this.disposeCount = 0;
    this.lastResolvedAt = null;
    this.snapshot = null;
    this.lastEnvelope = null;
    this.readyCount = 0;
    this.renderAckCount = 0;
    this.lastRenderAck = null;
    this.contractRejectionCount = 0;
    this.lastContractRejection = null;
    this.operationErrorCount = 0;
    this.lastOperationError = null;
    this.disposables = [];
  }

  preferences() {
    const raw = this.context.workspaceState.get(PREF_KEY, {});
    return {
      expandedWaveIds: Array.isArray(raw.expandedWaveIds) ? raw.expandedWaveIds : [],
      expandedTaskIds: Array.isArray(raw.expandedTaskIds) ? raw.expandedTaskIds : [],
      selectedProviderId: typeof raw.selectedProviderId === 'string' ? raw.selectedProviderId : null
    };
  }

  async savePreferences(next) {
    const current = this.preferences();
    await this.context.workspaceState.update(PREF_KEY, { ...current, ...next });
  }

  async reportClientError(code, detail) {
    try {
      await this.post({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'error', code, detail });
    } catch (error) {
      this.callbacks.onDiagnostic?.({ category: 'error-delivery-failed', detail: `sidebar-error-delivery-failed:code=${code};error=${String(error?.message || error || 'unknown').replace(/[\r\n]+/g, ' ').slice(0, 300)}` });
    }
  }

  resolveWebviewView(view) {
    this.view = view;
    this.resolveCount += 1;
    this.lastResolvedAt = new Date().toISOString();
    const webview = view.webview;
    webview.options = { enableScripts: true, localResourceRoots: [this.vscode.Uri.file(path.join(this.context.extensionPath, 'media'))] };
    webview.html = sidebarHtml(this.vscode, webview, this.context.extensionPath);
    this.disposables.push(webview.onDidReceiveMessage(message => { void this.receive(message); }));
    if (view.onDidChangeVisibility) this.disposables.push(view.onDidChangeVisibility(() => { void this.callbacks.onVisibilityChange?.(view.visible !== false); }));
    if (view.onDidDispose) this.disposables.push(view.onDidDispose(() => { this.disposeCount += 1; this.view = null; }));
  }

  async receive(raw) {
    let message;
    try {
      message = validateSidebarInbound(raw);
    } catch (error) {
      const detail = describeSidebarInboundRejection(raw, error);
      this.contractRejectionCount += 1;
      this.lastContractRejection = { detail, recordedAt: new Date().toISOString() };
      this.callbacks.onDiagnostic?.({ category: 'contract-rejected', detail });
      await this.reportClientError('contract-rejected', detail);
      return;
    }
    try {
      if (message.type === 'ready') {
        this.readyCount += 1;
        if (this.snapshot) await this.pushSnapshot(this.snapshot, true);
        else await this.callbacks.onReady?.();
        return;
      }
      if (message.type === 'rendered') {
        const expectedRevision = this.lastEnvelope?.projection?.revision;
        if (expectedRevision == null || message.revision !== expectedRevision) return;
        this.renderAckCount += 1;
        this.lastRenderAck = { ...message, recordedAt: new Date().toISOString() };
        return;
      }
      if (message.type === 'openControlPlane') return this.callbacks.openControlPlane?.('/control-plane');
      if (message.type === 'openEntity') return this.callbacks.openEntity?.(message.entityType, message.entityId);
      if (message.type === 'openPlanFromPunch') return this.callbacks.openEntity?.('plan', message.planId);
      if (message.type === 'retryConnection') return this.callbacks.retryConnection?.();
      if (message.type === 'toggleWave') {
        const ids = new Set(this.preferences().expandedWaveIds); message.expanded ? ids.add(message.waveId) : ids.delete(message.waveId);
        return this.savePreferences({ expandedWaveIds: [...ids].slice(0, 40) });
      }
      if (message.type === 'toggleTask') {
        const ids = new Set(this.preferences().expandedTaskIds); message.expanded ? ids.add(message.taskId) : ids.delete(message.taskId);
        return this.savePreferences({ expandedTaskIds: [...ids].slice(0, 80) });
      }
      if (message.type === 'selectProvider') {
        const providers = this.lastEnvelope?.projection?.providerState?.providers || [];
        if (message.providerId !== null && !providers.some(item => item.providerId === message.providerId)) throw new Error('selected-provider-is-not-in-current-projection');
        await this.savePreferences({ selectedProviderId: message.providerId });
        return this.pushSnapshot(this.snapshot, true);
      }
      if (message.type === 'providerPrevious' || message.type === 'providerNext') {
        const providers = this.lastEnvelope?.projection?.providerState?.providers || [];
        if (!providers.length) return;
        const current = providers.findIndex(item => item.providerId === this.preferences().selectedProviderId);
        const step = message.type === 'providerPrevious' ? -1 : 1;
        const index = (Math.max(0, current) + step + providers.length) % providers.length;
        await this.savePreferences({ selectedProviderId: providers[index].providerId });
        return this.pushSnapshot(this.snapshot, true);
      }
    } catch (error) {
      const detail = `sidebar-operation-failed:type=${message.type};error=${String(error?.message || error || 'unknown').replace(/[\r\n]+/g, ' ').slice(0, 380)}`;
      this.operationErrorCount += 1;
      this.lastOperationError = { detail, recordedAt: new Date().toISOString() };
      this.callbacks.onDiagnostic?.({ category: 'operation-failed', detail });
      await this.reportClientError('operation-failed', detail);
    }
  }

  async post(message) {
    const outbound = validateSidebarOutbound(message);
    if (this.view?.visible !== false) await this.view?.webview.postMessage(outbound);
  }

  async pushSnapshot(snapshot, force = false) {
    this.snapshot = snapshot;
    let preferences = this.preferences();
    let projection = buildSidebarProjection(snapshot, preferences);
    const selected = projection.providerState.providers.find(item => item.providerId === projection.ui.selectedProviderId);
    const active = projection.providerState.providers.find(item => item.activityState === 'active' && !item.stale);
    if (active && !selected) {
      await this.savePreferences({ selectedProviderId: active.providerId });
      preferences = this.preferences();
      projection = buildSidebarProjection(snapshot, preferences);
    }
    const envelope = validateSidebarOutbound({
      schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot',
      capabilities: { renderAcknowledgement: true, assetProtocol: SIDEBAR_ASSET_PROTOCOL }, projection
    });
    const serialized = JSON.stringify(envelope);
    if (!force && serialized === this.lastSerialized) return projection;
    this.lastSerialized = serialized; this.lastEnvelope = envelope;
    if (this.view) await this.view.webview.postMessage(envelope);
    return projection;
  }

  hasVisibleView() { return Boolean(this.view && this.view.visible !== false); }

  inspect() {
    return {
      schema_version: 'px.sidebar-provider-inspection/1.0',
      resolved: Boolean(this.view),
      visible: Boolean(this.view && this.view.visible !== false),
      resolve_count: this.resolveCount,
      dispose_count: this.disposeCount,
      last_resolved_at: this.lastResolvedAt,
      html_assigned: Boolean(this.view?.webview?.html),
      ready_count: this.readyCount,
      render_ack_count: this.renderAckCount,
      rendered: this.lastRenderAck ? { ...this.lastRenderAck } : null,
      contract_rejection_count: this.contractRejectionCount,
      last_contract_rejection: this.lastContractRejection ? { ...this.lastContractRejection } : null,
      operation_error_count: this.operationErrorCount,
      last_operation_error: this.lastOperationError ? { ...this.lastOperationError } : null
    };
  }

  static taskSubtaskRecord(parentTask, parentSafeId, subtask, index) {
    const subtaskIndex = Number.isFinite(Number(index)) ? Number(index) + 1 : 1;
    const safeId = (value, fallback = 'task') => {
      const text = String(value ?? '').trim();
      return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(text) ? text : fallback;
    };
    const fallbackName = `${parentSafeId}-subtask-${subtaskIndex}`;
    const rawSubtaskId = safeId(subtask?.id, fallbackName);
    const normalizedSubtaskId = rawSubtaskId.startsWith(`${parentSafeId}.`) ? rawSubtaskId.slice(parentSafeId.length + 1) : rawSubtaskId;
    return {
      ...subtask,
      id: `${parentSafeId}.${normalizedSubtaskId}`,
      parentTaskId: parentSafeId,
      parentTaskName: parentTask?.name || parentTask?.title
    };
  }

  entityRecord(entityType, entityId) {
    const projection = this.lastEnvelope?.projection;
    if (!projection) return null;
    const safeId = (value, fallback = 'task') => {
      const text = String(value ?? '').trim();
      return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(text) ? text : fallback;
    };
    const taskRows = (projection.waves || []).flatMap((wave, waveIndex) => (wave?.tasks || []).flatMap((task, taskIndex) => {
      const parentSafeId = safeId(task?.id, `task-${waveIndex + 1}-${taskIndex + 1}`);
      const children = Array.isArray(task?.subtasks) ? task.subtasks : [];
      return [{ ...task, id: parentSafeId }, ...children.map((subtask, subtaskIndex) => SidebarViewProvider.taskSubtaskRecord(task, parentSafeId, subtask, subtaskIndex))];
    }));
    const collections = {
      plan: [projection.execution, projection.lastRun].filter(Boolean).map(item => ({ ...item, id: item.planId })),
      wave: projection.waves,
      task: taskRows,
      agent: projection.agents.map(item => ({ ...item, id: item.agentId })),
      orchestration: projection.orchestrations,
      provider: projection.providerState.providers.map(item => ({ ...item, id: item.providerId })),
      attention: projection.attention
    };
    const record = (collections[entityType] || []).find(item => item?.id === entityId);
    return record ? JSON.parse(JSON.stringify(record)) : null;
  }

  dispose() { for (const disposable of this.disposables.splice(0)) disposable?.dispose?.(); this.view = null; }
}

module.exports = { SidebarViewProvider, sidebarHtml, PREF_KEY };
