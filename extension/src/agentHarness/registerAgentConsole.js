'use strict';

const { CanonicalEventBus } = require('./eventBus');
const { TaskStore } = require('./taskStore');
const { ProjectTaskStore } = require('./projectTaskStore');
const { BudgetLedger } = require('./budgetLedger');
const { ProjectBudgetLedger } = require('./projectBudgetLedger');
const { WorkerRegistry } = require('./workerRegistry');
const { ContextCompiler } = require('./contextCompiler');
const { TinyLibrarian } = require('./tinyLibrarian');
const { ToolBroker } = require('./toolBroker');
const { HarnessController } = require('./harnessController');
const { AgentConsoleViewProvider } = require('./agentConsoleView');
const { OllamaAdapter } = require('./adapters/ollama');
const { PxProviderGatewayAdapter } = require('./adapters/pxProviderGateway');
const { registerVsCodeReadOnlyTools } = require('./vscodeTools');

const { WorkerDescriptor, parse } = require('./contracts');

const LANE_CAPABILITIES = Object.freeze({
  control: { coding: 0.4, planning: 0.5, review: 0.4, classification: 0.7 },
  fast: { coding: 0.6, planning: 0.5, review: 0.5, classification: 0.5 },
  balanced: { coding: 0.7, planning: 0.7, review: 0.6, classification: 0.5 },
  deep: { coding: 0.8, planning: 0.8, review: 0.7, classification: 0.6 }
});
const LANE_RELIABILITY = Object.freeze({ control: 0.6, fast: 0.6, balanced: 0.55, deep: 0.5 });
const LANE_LATENCY = Object.freeze({ control: 'fast', fast: 'fast', balanced: 'medium', deep: 'slow' });

function safeToken(value, fallback) {
  const token = typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/.test(value) ? value : null;
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
  const worker = {
    workerId: `px-fabric-${profileId}`,
    adapterId: 'px-provider-gateway',
    providerId: safeToken(row.provider_id, 'llama.cpp'),
    modelId,
    profileId,
    displayName: `${modelId} (${lane} lane)`,
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
  try { return parse(WorkerDescriptor, worker, 'fabric-worker'); } catch { return null; }
}

function projectFabricCatalog(listResponse) {
  const rows = Array.isArray(listResponse?.models) ? listResponse.models : [];
  const seen = new Set();
  const workers = [];
  for (const row of rows.slice(0, 256)) {
    const worker = projectFabricModel(row);
    if (!worker || seen.has(worker.workerId)) continue;
    seen.add(worker.workerId);
    workers.push(worker);
  }
  return workers.sort((a, b) => b.contextLimit - a.contextLimit || a.workerId.localeCompare(b.workerId));
}

const TASK_STATE_KEY = 'pacifyX.agentConsole.taskState.v1';
const BUDGET_STATE_KEY = 'pacifyX.agentConsole.budgetState.v1';

function registerAgentConsole(vscode, context, options = {}) {
  const disposables = []; let disposed = false;
  const eventBus = new CanonicalEventBus();
  const taskStore = options.nativeTaskState === true
    ? new ProjectTaskStore({ rootsProvider: options.workspaceRootsProvider,
      legacySnapshot: context.workspaceState.get(TASK_STATE_KEY) ?? null,
      legacyRootProvider: options.legacyTaskRootProvider })
    : new TaskStore({ persistence: { load: () => context.workspaceState.get(TASK_STATE_KEY), save: value => context.workspaceState.update(TASK_STATE_KEY, value) } });
  const hostSettings = options.settingsProvider || (() => ({}));
  const budgetLedger = options.nativeTaskState === true ? new ProjectBudgetLedger(taskStore, () => hostSettings().executionPolicy || {}) : new BudgetLedger(() => hostSettings().executionPolicy || {}, {
    persistence: { load: () => context.workspaceState.get(BUDGET_STATE_KEY), save: value => context.workspaceState.update(BUDGET_STATE_KEY, value) },
    // Existing tasks have no durable historical usage in the old host. Keep
    // their paid dispatch blocked; a missing ledger is never proof of zero.
    legacyTaskIds: taskStore.listTasks().map(task => task.taskId)
  });
  const workerRegistry = new WorkerRegistry();
  const contextCompiler = new ContextCompiler({ retrievalProvider: options.retrievalProvider || null }); const tinyLibrarian = new TinyLibrarian({ modelRunner: options.tinyModelRunner || null });
  const toolBroker = new ToolBroker({ taskStore, eventBus, approvalProvider: options.approvalProvider || null });
  const harness = new HarnessController({ eventBus, taskStore, budgetLedger, workerRegistry, contextCompiler, tinyLibrarian, toolBroker, hostSettings });

  if (typeof options.activityObserver === 'function') disposables.push(eventBus.subscribe(event => {
    try { options.activityObserver({ category: 'agent-harness', operation: event.type, status: mapActivityStatus(event.status), effect: 'observe', correlationId: event.runId || event.taskId || event.eventId, taskId: event.taskId || undefined, source: 'px-agent-console', metadata: { event_id: event.eventId, sequence: event.sequence, worker_id: event.workerId, summary_sha256: require('./ids').sha256(event.summary || ''), payload_keys: Object.keys(event.payload || {}).sort().slice(0,40) } }, { attributeClaim: true, listenerId: 'px-agent-console' }); } catch { /* activity authority remains optional during bring-up */ }
  }));

  const settings = hostSettings();
  // Source templates supply labels/preferences, never native receipt identity.
  const templates = options.gatewayWorkers || [];
  const fabricCatalog = typeof options.modelFabricLister === 'function';
  const dynamicCatalog = !fabricCatalog && typeof options.gatewayWorkerCatalog === 'function';
  const modelCatalog = { state: fabricCatalog ? 'refreshing' : 'unmanaged', detail: 'No canonical catalog observation yet.', source: fabricCatalog ? 'model-fabric' : 'host-templates', updatedAt: null };
  let refreshGeneration = 0, view = null;
  const bindings = new Map(); let refreshing = null;
  function install(template, values, revision = '') {
    const worker = { ...template, ...values };
    const identity = JSON.stringify([worker, revision]);
    if (bindings.get(worker.workerId)?.identity === identity) return;
    bindings.get(worker.workerId)?.registration.dispose();
    const adapter = new PxProviderGatewayAdapter({ worker, invokeProvider: options.providerGatewayInvoker, healthProvider: options.providerGatewayHealth });
    const registration = workerRegistry.register(worker, adapter);
    bindings.set(worker.workerId, { identity, registration });
  }
  for (const template of fabricCatalog ? [] : templates) {
    if (typeof options.providerGatewayInvoker !== 'function') break;
    install(template, dynamicCatalog ? { enabled: false } : {});
  }
  if (dynamicCatalog) {
    harness.refreshWorkers = () => {
      if (disposed) return Promise.reject(new Error('native-worker-catalog-disposed'));
      if (refreshing) return refreshing;
      refreshing = Promise.resolve().then(() => options.gatewayWorkerCatalog()).then(catalog => {
        if (disposed) throw new Error('native-worker-catalog-disposed');
        if (catalog?.schema_version !== 'px.vscode-model-list/1.0' || catalog.authority_granted !== false ||
            !Array.isArray(catalog.models) || catalog.models.length > 256) throw new Error('native-worker-catalog-invalid');
        const plans = templates.map(template => {
          const matches = catalog.models.filter(row => row?.profile_id === template.profileId);
          if (matches.length > 1) throw new Error('native-worker-catalog-ambiguous-profile');
          const row = matches[0]; const hex = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
          const valid = row && row.available !== false && row.provider_id === 'llama.cpp' && row.adapter_id === 'llama-cpp-stream' &&
            hex(row.model_sha256) && hex(row.profile_sha256) && Number.isSafeInteger(row.context_tokens) && row.context_tokens > 0 &&
            Number.isSafeInteger(row.max_output_tokens) && row.max_output_tokens > 0 && row.max_output_tokens <= row.context_tokens;
          return { template, row, values: valid ? { providerId: row.provider_id, modelId: row.model_sha256,
            contextLimit: row.context_tokens, maxOutputTokens: row.max_output_tokens, enabled: true, costClass: 'local', locality: 'local' }
            : { enabled: false } };
        });
        for (const plan of plans) install(plan.template, plan.values, plan.values.enabled ? plan.row.profile_sha256 : 'unavailable');
      }).catch(error => {
        if (!disposed) for (const template of templates) {
          install(template, { enabled: false }, 'catalog-failed');
          workerRegistry.setHealth(template.workerId, { status: 'unavailable', detail: 'Native model catalog unavailable; refresh required.' });
        }
        throw new Error('native-worker-catalog-unavailable', { cause: error });
      }).finally(() => { refreshing = null; });
      return refreshing;
    };
  }
  function clearFabricWorkers() {
    for (const value of bindings.values()) value.registration.dispose();
    bindings.clear();
  }
  async function refreshModelCatalog() {
    if (disposed) return [];
    if (!fabricCatalog) { await harness.refreshWorkers?.(); return workerRegistry.list().map(w => w.workerId); }
    const generation = ++refreshGeneration;
    clearFabricWorkers();
    Object.assign(modelCatalog, { state: 'refreshing', detail: 'Refreshing the canonical model catalog.' });
    try {
      if (typeof options.providerGatewayInvoker !== 'function') throw new Error('provider-gateway-unavailable');
      const listed = await options.modelFabricLister();
      if (disposed || generation !== refreshGeneration) return [];
      if (listed?.schema_version !== 'px.vscode-model-list/1.0' || listed.authority_granted !== false ||
          !Array.isArray(listed.models) || listed.models.length > 256) throw new Error('native-worker-catalog-invalid');
      // Conflicting identities may not win by input ordering.
      const identities = new Map();
      for (const row of listed.models) {
        if (!row || typeof row.profile_id !== 'string') continue;
        const identity = JSON.stringify(row);
        if (identities.has(row.profile_id) && identities.get(row.profile_id) !== identity) throw new Error('native-worker-catalog-ambiguous-profile');
        identities.set(row.profile_id, identity);
      }
      const hex = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
      const workers = projectFabricCatalog(listed);
      for (const worker of workers) {
        const row = listed.models.find(row => row?.profile_id === worker.profileId);
        const valid = worker.bridge.bridgeKind === 'local' && row.available !== false &&
          row.provider_id === 'llama.cpp' && row.adapter_id === 'llama-cpp-stream' &&
          hex(row.model_sha256) && hex(row.profile_sha256) &&
          typeof row.session_id === 'string' && row.session_id.startsWith('local-model-session-') &&
          Number.isSafeInteger(row.context_tokens) && row.context_tokens > 0 &&
          Number.isSafeInteger(row.max_output_tokens) && row.max_output_tokens > 0 && row.max_output_tokens <= row.context_tokens;
        install(worker, valid ? { modelId: row.model_sha256, maxOutputTokens: row.max_output_tokens, enabled: true } : { enabled: false }, JSON.stringify([row.profile_sha256, row.session_id]));
      }
      Object.assign(modelCatalog, { state: 'current', detail: `${workers.length} models reported by the canonical fabric; availability remains governed by native identity and readiness.`, updatedAt: new Date().toISOString() });
      return workers.map(worker => worker.workerId);
    } catch (error) {
      if (disposed || generation !== refreshGeneration) return [];
      clearFabricWorkers();
      Object.assign(modelCatalog, { state: 'unavailable', detail: `model-fabric-list-failed:${String(error?.message || error).slice(0, 200)}`, updatedAt: new Date().toISOString() });
      return [];
    } finally {
      if (!disposed && generation === refreshGeneration) {
        await workerRegistry.refreshHealth();
        await view?.publish();
      }
    }
  }
  if (fabricCatalog) harness.refreshWorkers = refreshModelCatalog;
  disposables.push({ dispose() { for (const value of bindings.values()) value.registration.dispose(); bindings.clear(); } });
  // Contained bring-up path only. Do not enable this when the canonical PX provider
  // gateway is available for the same local model route.
  if (settings.ollamaEnabled && options.ollamaModel && options.allowDirectOllamaBringup === true) {
    disposables.push(workerRegistry.register({ workerId: `ollama-${safeModelId(options.ollamaModel)}`, adapterId: 'ollama-direct-bringup', providerId: 'ollama-local', modelId: options.ollamaModel, displayName: `Ollama bring-up Â· ${options.ollamaModel}`,
      costClass: 'local', contextLimit: options.ollamaContextLimit || null, locality: 'local', capabilities: { coding: 0.5, planning: 0.5, review: 0.5, classification: 0.5, toolUse: false, vision: false, structuredOutput: false }, supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 0.5, latencyClass: 'unknown' },
      new OllamaAdapter({ baseUrl: settings.ollamaBaseUrl, model: options.ollamaModel })));
  }

  disposables.push(registerVsCodeReadOnlyTools(vscode, toolBroker, options.workspaceRootProvider));
  const sandboxControl = options.sandboxControl || (typeof options.onSandboxModeChanged === 'function' ? async ({ mode, allowedEndpoints }) => {
    const sandbox = require('../isolatedAgentSandbox');
    const previous = sandbox.currentSandboxSelection();
    if (previous.mode !== 'ON' && mode === 'ON') {
      const answer = await vscode.window.showWarningMessage('Select sandbox policy mode ON?', {
        modal: true, detail: 'This saves and publishes policy selection. Publication does not prove process or network containment is enforced.'
      }, 'Select policy ON');
      if (answer !== 'Select policy ON') throw new Error('sandbox-policy-selection-cancelled');
    }
    await sandbox.setSandboxMode(mode);
    if (allowedEndpoints !== undefined) await sandbox.setAllowedEndpoints(allowedEndpoints);
    await options.onSandboxModeChanged(sandbox.buildSandboxPolicyRequest());
  } : undefined);
  view = new AgentConsoleViewProvider(vscode, context, { harness, workspaceRootProvider: options.workspaceRootProvider, openControlPlane: options.openControlPlane, onDiagnostic: options.onDiagnostic,
    modelCatalog, refreshModelCatalog, tieControl: options.tieControl, sandboxControl,
    inspectPreparedGroup: options.inspectPreparedGroup, executePreparedGroup: options.executePreparedGroup });
  disposables.push(vscode.window.registerWebviewViewProvider('pacifyX.agentConsole', view, { webviewOptions: { retainContextWhenHidden: true } }), view);
  disposables.push(vscode.commands.registerCommand('pacifyX.openAgentConsole', () => vscode.commands.executeCommand('pacifyX.agentConsole.focus')));
  disposables.push(vscode.commands.registerCommand('pacifyX.newAgentTask', async () => { const goal = await vscode.window.showInputBox({ title: 'New PX Agent Task', prompt: 'Task goal' }); if (goal) { harness.createTask({ goal, mode: 'ASK', maxEffectClass: 'READ_ONLY', contextBudgetTokens: settings.contextInjectionCapTokens || 12000, taskCostCeilingUsd: settings.executionPolicy?.max_cost_per_task_usd ?? null, localFirst: settings.executionPolicy?.local_first !== false, requireApprovalBeforeBillable: settings.executionPolicy?.require_approval_before_billable_execution !== false }); await vscode.commands.executeCommand('pacifyX.agentConsole.focus'); } }));
  if (fabricCatalog) void refreshModelCatalog();
  else void workerRegistry.refreshHealth().catch(() => {});

  return { harness, refreshModelCatalog, modelCatalog, dispose() { disposed = true; harness.dispose(); for (const d of disposables.splice(0)) d?.dispose?.(); } };
}

function safeModelId(value) { return String(value || 'model').toLowerCase().replace(/[^a-z0-9._:-]+/g, '-').slice(0, 100) || 'model'; }
function mapActivityStatus(value) { return value === 'succeeded' ? 'succeeded' : value === 'failed' ? 'failed' : value === 'cancelled' ? 'cancelled' : value === 'started' ? 'started' : 'progress'; }

module.exports = { projectFabricCatalog, projectFabricModel, registerAgentConsole, TASK_STATE_KEY, BUDGET_STATE_KEY };
