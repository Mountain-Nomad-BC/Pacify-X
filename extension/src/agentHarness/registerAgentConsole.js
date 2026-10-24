'use strict';
const { CanonicalEventBus } = require('./eventBus');
const { TaskStore } = require('./taskStore');
const { DurableTaskState } = require('./durableTaskState');
const { migrateLegacyTaskState } = require('./legacyTaskMigration');
const { BudgetLedger } = require('./budgetLedger');
const { WorkerRegistry } = require('./workerRegistry');
const { ContextCompiler } = require('./contextCompiler');
const { PXArchivist } = require('./tinyLibrarian');
const { ToolBroker } = require('./toolBroker');
const { HarnessController } = require('./harnessController');
const { AgentConsoleViewProvider } = require('./agentConsoleView');
const isolatedSandbox = require('../isolatedAgentSandbox');
const { OllamaAdapter } = require('./adapters/ollama');
const { PxProviderGatewayAdapter } = require('./adapters/pxProviderGateway');
const { registerVsCodeReadOnlyTools } = require('./vscodeTools');
const TASK_STATE_KEY = 'pacifyX.agentConsole.taskState.v1';

// The console's selectable model surface is a projection of PX's canonical model fabric,
// never a private literal. `runtime.vscode_model_bridge list` already returns exactly the
// profiles that are certified, bound to the running governed router session, and loaded, so
// it is the only authority allowed to decide what the operator may select or Auto may rank.
// A profile PX has not admitted is projected as unavailable rather than hidden, so the UI
// never claims capacity that runtime cannot honour.

// Relative capability weight per canonical model-fabric lane. PX publishes lane identity,
// not a capability score, so this mapping is an explicit, reviewable projection rather than
// an invented measurement.
const LANE_CAPABILITIES = Object.freeze({
  control: { coding: 0.4, planning: 0.5, review: 0.4, classification: 0.7 },
  fast: { coding: 0.6, planning: 0.5, review: 0.5, classification: 0.5 },
  balanced: { coding: 0.7, planning: 0.7, review: 0.6, classification: 0.5 },
  deep: { coding: 0.8, planning: 0.8, review: 0.7, classification: 0.6 }
});
const LANE_RELIABILITY = Object.freeze({ control: 0.6, fast: 0.6, balanced: 0.55, deep: 0.5 });
const LANE_LATENCY = Object.freeze({ control: 'fast', fast: 'fast', balanced: 'medium', deep: 'slow' });

function safeToken(value, fallback) {
  const token = String(value == null ? '' : value).replace(/[^A-Za-z0-9._:-]+/g, '-').replace(/^[^A-Za-z0-9]+/, '').slice(0, 100);
  return token || fallback;
}

// Project one canonical model-fabric row into a PX worker descriptor.
// `available` false means PX reported the row but the bridge could not confirm it right now;
// it is still projected so the operator can see the gap rather than lose it silently.
function projectFabricModel(row) {
  if (!row || typeof row !== 'object') return null;
  const profileId = safeToken(row.profile_id, null);
  const modelId = typeof row.model_id === 'string' && row.model_id.length > 0 && row.model_id.length <= 240 ? row.model_id : null;
  if (!profileId || !modelId) return null;
  const remote = row.bridge_kind === 'remote';
  if (remote && (!({ custom: 'custom-openai-chat', openai: 'openai-responses', mistral: 'mistral-chat', claude: 'claude-anthropic-messages' }[row.provider_id] === row.adapter_id) || row.locality !== 'remote' || row.cost_class !== 'billable-api' || !/^[a-f0-9]{64}$/.test(row.profile_sha256 || '') || row.model_sha256 != null || !row.capabilities || row.available !== false)) return null;
  const lane = String(row.lane || 'unknown');
  const contextLimit = Number.isInteger(row.context_tokens) && row.context_tokens > 0 ? row.context_tokens : null;
  const capabilities = LANE_CAPABILITIES[lane] || { coding: 0.3, planning: 0.3, review: 0.3, classification: 0.3 };
  return {
    workerId: `px-fabric-${profileId}`,
    adapterId: 'px-provider-gateway',
    providerId: safeToken(row.provider_id, 'llama.cpp'),
    modelId,
    profileId,
    displayName: `${modelId} · ${lane} lane`,
    costClass: remote ? row.cost_class : 'local',
    contextLimit,
    locality: remote ? row.locality : 'local',
    capabilities: remote ? row.capabilities : {
      coding: capabilities.coding,
      planning: capabilities.planning,
      review: capabilities.review,
      classification: capabilities.classification,
      // Tool authority is never inherited from the model fabric. VS Code tools are gated
      // separately by the harness ToolBroker and its approval policy.
      toolUse: false,
      vision: row.image_input === true,
      structuredOutput: true
    },
    // The governed local bridge serves text generation only; every effect still passes the
    // harness effect-class admission and the PX operation/approval owners.
    supportedEffectClass: 'READ_ONLY',
    enabled: row.available !== false,
    reliability: LANE_RELIABILITY[lane] ?? 0.45,
    latencyClass: LANE_LATENCY[lane] ?? 'unknown',
    bridge: {
      bridgeKind: remote ? 'remote' : 'local',
      profileSha256: remote ? row.profile_sha256 : null,
      lane,
      sessionId: typeof row.session_id === 'string' ? row.session_id : null,
      adapterId: typeof row.adapter_id === 'string' ? row.adapter_id : null,
      modelSha256: typeof row.model_sha256 === 'string' ? row.model_sha256 : null,
      contextTokens: contextLimit,
      maxOutputTokens: Number.isInteger(row.max_output_tokens) ? row.max_output_tokens : null,
      toolCalling: row.tool_calling === true,
      imageInput: row.image_input === true,
      available: row.available !== false,
      unavailableReason: typeof row.unavailable_reason === 'string' ? row.unavailable_reason : null
    }
  };
}

function projectFabricCatalog(listResponse) {
  const rows = Array.isArray(listResponse?.models) ? listResponse.models : [];
  const seen = new Set();
  const workers = [];
  for (const row of rows) {
    const worker = projectFabricModel(row);
    if (!worker || seen.has(worker.workerId)) continue;
    seen.add(worker.workerId);
    workers.push(worker);
  }
  return workers.sort((a, b) => b.contextLimit - a.contextLimit || a.workerId.localeCompare(b.workerId));
}

function registerAgentConsole(vscode, context, options = {}) {
  const disposables = [];
  const eventBus = new CanonicalEventBus();
  const projectRoot = options.workspaceRootProvider?.();
  const taskPersistence = projectRoot ? new DurableTaskState(projectRoot) : {
    load: () => context.workspaceState.get(TASK_STATE_KEY), save: value => context.workspaceState.update(TASK_STATE_KEY, value)
  };
  const taskStore = new TaskStore({ persistence: taskPersistence });
  // Reconcile any legacy workspaceState task state into the native durable store.
  // Additive, hash-bound and idempotent; the legacy snapshot is retained, never deleted.
  let legacyMigration = null;
  if (projectRoot && typeof context.workspaceState?.get === 'function') {
    try {
      legacyMigration = migrateLegacyTaskState(projectRoot, context.workspaceState.get(TASK_STATE_KEY), taskStore);
    } catch (error) {
      legacyMigration = { schemaVersion: 'px.legacy-task-migration/1.0', status: 'FAILED', failure_type: error.name, reason: String(error.message || '').slice(0, 500), authority_granted: false };
    }
  }
  const hostSettings = options.settingsProvider || (() => ({}));
  const budgetLedger = new BudgetLedger(() => hostSettings().executionPolicy || {}); const workerRegistry = new WorkerRegistry();
  const contextCompiler = new ContextCompiler({ retrievalProvider: options.retrievalProvider || null });
  const experienceKey = 'pacifyX.agentConsole.tieExperience.v1';
  let experienceWrite = Promise.resolve();
  const experienceStore = {
    load: async taskId => { await experienceWrite; return context.workspaceState.get(experienceKey, {})[taskId] || []; },
    save: (taskId, rows) => {
      const write = experienceWrite.then(async () => {
        const records = { ...context.workspaceState.get(experienceKey, {}) };
        delete records[taskId]; records[taskId] = rows.slice(-8);
        const entries = Object.entries(records).slice(-64);
        await context.workspaceState.update(experienceKey, Object.fromEntries(entries));
      });
      experienceWrite = write.catch(() => {});
      return write;
    }
  };
  const tinyLibrarian = new PXArchivist({ modelRunner: options.archivistModelRunner || options.tinyModelRunner || null, experienceStore });
  const toolBroker = new ToolBroker({ eventBus, approvalProvider: options.approvalProvider || null });
  const harness = new HarnessController({ eventBus, taskStore, budgetLedger, workerRegistry, contextCompiler, tinyLibrarian, toolBroker, hostSettings,
    projectId: options.projectId || (projectRoot ? require('node:path').basename(projectRoot) : 'workspace') });
  // Isolated Agent Sandbox: expose the current selection to the console so the top
  // Chat Settings dropdown and the Side Panel Control Panel read the SAME value
  // from the ONE owner. Both surfaces write through sandboxControl below.
  harness.sandboxState = () => isolatedSandbox.currentSandboxSelection();

  if (typeof options.activityObserver === 'function') disposables.push(eventBus.subscribe(event => {
    try { options.activityObserver({ category: 'agent-harness', operation: event.type, status: mapActivityStatus(event.status), effect: 'observe', correlationId: event.runId || event.taskId || event.eventId, taskId: event.taskId || undefined, source: 'px-agent-console', metadata: { event_id: event.eventId, sequence: event.sequence, worker_id: event.workerId, summary_sha256: require('./ids').sha256(event.summary || ''), payload_keys: Object.keys(event.payload || {}).sort().slice(0,40) } }, { attributeClaim: true, listenerId: 'px-agent-console' }); } catch { /* activity authority remains optional during bring-up */ }
  }));

  const settings = hostSettings();
  // Preferred: workers backed by PX's canonical provider gateway.
  //
  // The catalog is owned by `runtime.vscode_model_bridge list`. When a model-fabric lister
  // is supplied the console mirrors that canonical answer instead of trusting any local
  // literal, and re-mirrors on refresh so newly admitted or newly unloaded profiles appear
  // without a host reload. Selection policy stays entirely in router.js.
  const gatewayDisposables = new Map();
  const catalog = {
    state: 'idle',
    detail: 'Model fabric has not been queried yet.',
    source: typeof options.modelFabricLister === 'function' ? 'model-fabric' : 'static-literal',
    updatedAt: null
  };
  const adapterFor = worker => new PxProviderGatewayAdapter({ worker, invokeProvider: options.providerGatewayInvoker, healthProvider: options.providerGatewayHealth });

  let refreshGeneration = 0;
  function clearFabricWorkers() {
    for (const disposable of gatewayDisposables.values()) disposable.dispose?.();
    gatewayDisposables.clear();
  }

  function syncFabricWorkers(descriptors) {
    if (typeof options.providerGatewayInvoker !== 'function') {
      clearFabricWorkers();
      catalog.state = 'unavailable';
      catalog.detail = 'PX provider gateway invoker is not connected.';
      return [];
    }
    const next = new Map();
    for (const descriptor of descriptors) {
      if (next.has(descriptor.workerId)) continue;
      try {
        next.set(descriptor.workerId, workerRegistry.register(descriptor, adapterFor(descriptor)));
      } catch (error) {
        // A model PX reports but cannot describe as a valid worker is projected as absent
        // rather than allowed to fail the whole catalog refresh.
        catalog.detail = `worker-descriptor-rejected:${String(error?.message || error).slice(0, 200)}`;
      }
    }
    for (const [workerId, disposable] of gatewayDisposables) {
      if (!next.has(workerId)) { disposable.dispose?.(); gatewayDisposables.delete(workerId); }
    }
    for (const [workerId, disposable] of next) gatewayDisposables.set(workerId, disposable);
    return [...next.keys()];
  }

  async function refreshModelCatalog() {
    if (typeof options.modelFabricLister !== 'function') {
      catalog.state = 'unmanaged';
      catalog.detail = 'No model fabric lister is connected; the catalog is a static literal.';
      return [];
    }
    const generation = ++refreshGeneration;
    clearFabricWorkers();
    catalog.state = 'refreshing';
    try {
      const listed = await options.modelFabricLister();
      if (generation !== refreshGeneration) return [];
      const registered = syncFabricWorkers(projectFabricCatalog(listed));
      if (typeof options.providerGatewayInvoker !== 'function') return [];
      catalog.state = 'current';
      catalog.detail = registered.length
        ? `${registered.length} certified, loaded model${registered.length === 1 ? '' : 's'} projected from the canonical model fabric.`
        : 'The canonical model fabric reports no certified, loaded models right now.';
      catalog.updatedAt = new Date().toISOString();
      return registered;
    } catch (error) {
      if (generation !== refreshGeneration) return [];
      clearFabricWorkers();
      catalog.state = 'unavailable';
      catalog.detail = `model-fabric-list-failed:${String(error?.code || error?.message || error).slice(0, 200)}`;
      catalog.updatedAt = new Date().toISOString();
      return [];
    } finally {
      void workerRegistry.refreshHealth().catch(() => {});
      // `view` is constructed after the first refresh is kicked off; publish only once it exists.
      if (typeof view !== 'undefined' && view) view.publish().catch(() => {});
    }
  }

  if (typeof options.modelFabricLister === 'function') {
    void refreshModelCatalog();
  } else {
    for (const descriptor of options.gatewayWorkers || []) {
      if (typeof options.providerGatewayInvoker !== 'function') break;
      const worker = { ...descriptor };
      gatewayDisposables.set(worker.workerId, workerRegistry.register(worker, adapterFor(worker)));
    }
  }
  // Contained bring-up path only. Do not enable this when the canonical PX provider
  // gateway is available for the same local model route.
  if (settings.ollamaEnabled && options.ollamaModel && options.allowDirectOllamaBringup === true) {
    disposables.push(workerRegistry.register({ workerId: `ollama-${safeModelId(options.ollamaModel)}`, adapterId: 'ollama-direct-bringup', providerId: 'ollama-local', modelId: options.ollamaModel, displayName: `Ollama bring-up · ${options.ollamaModel}`,
      costClass: 'local', contextLimit: options.ollamaContextLimit || null, locality: 'local', capabilities: { coding: 0.5, planning: 0.5, review: 0.5, classification: 0.5, toolUse: false, vision: false, structuredOutput: false }, supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 0.5, latencyClass: 'unknown' },
      new OllamaAdapter({ baseUrl: settings.ollamaBaseUrl, model: options.ollamaModel })));
  }

  let view = null;
  disposables.push(registerVsCodeReadOnlyTools(vscode, toolBroker, options.workspaceRootProvider));
  view = new AgentConsoleViewProvider(vscode, context, { harness, openControlPlane: options.openControlPlane, onDiagnostic: options.onDiagnostic, modelCatalog: catalog, refreshModelCatalog, tieControl: options.tieControl,
    inspectPreparedGroup: options.inspectPreparedGroup,
    // The chat dropdown and control panel use one policy publisher. A successful
    // publish stores policy input; it does not attest platform enforcement.
    sandboxControl: async ({ mode, allowedEndpoints }) => {
      const normalized = await isolatedSandbox.setSandboxMode(mode);
      if (Array.isArray(allowedEndpoints)) await isolatedSandbox.setAllowedEndpoints(allowedEndpoints);
      if (typeof options.onSandboxModeChanged === 'function') {
        try { await options.onSandboxModeChanged(isolatedSandbox.buildSandboxPolicyRequest()); }
        catch (error) { throw new Error(`sandbox-runtime-publish-failed:${String(error?.message || error).slice(0, 300)}`); }
      }
      return normalized;
    } });
  disposables.push(vscode.window.registerWebviewViewProvider('pacifyX.agentConsole', view, { webviewOptions: { retainContextWhenHidden: true } }), view);
  disposables.push(vscode.commands.registerCommand('pacifyX.openAgentConsole', () => vscode.commands.executeCommand('pacifyX.agentConsole.focus')));
  disposables.push(vscode.commands.registerCommand('pacifyX.newAgentTask', async () => { const goal = await vscode.window.showInputBox({ title: 'New PX Agent Task', prompt: 'Task goal' }); if (goal) { harness.createTask({ goal, mode: 'ASK', maxEffectClass: 'READ_ONLY', contextBudgetTokens: settings.contextInjectionCapTokens || 12000, taskCostCeilingUsd: settings.executionPolicy?.max_cost_per_task_usd || null, localFirst: settings.executionPolicy?.local_first !== false, requireApprovalBeforeBillable: settings.executionPolicy?.require_approval_before_billable_execution !== false }); await vscode.commands.executeCommand('pacifyX.agentConsole.focus'); } }));
  void workerRegistry.refreshHealth().catch(() => {});

  return { harness, refreshModelCatalog, modelCatalog: catalog, dispose() { for (const d of gatewayDisposables.values()) d.dispose?.(); gatewayDisposables.clear(); harness.dispose(); for (const d of disposables.splice(0)) d?.dispose?.(); } };
}

function safeModelId(value) { return String(value || 'model').toLowerCase().replace(/[^a-z0-9._:-]+/g, '-').slice(0, 100) || 'model'; }
function mapActivityStatus(value) { return value === 'succeeded' ? 'succeeded' : value === 'failed' ? 'failed' : value === 'cancelled' ? 'cancelled' : value === 'started' ? 'started' : 'progress'; }

module.exports = { registerAgentConsole, projectFabricCatalog, projectFabricModel, TASK_STATE_KEY };
