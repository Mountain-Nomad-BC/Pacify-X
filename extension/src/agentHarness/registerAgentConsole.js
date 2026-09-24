'use strict';

const { CanonicalEventBus } = require('./eventBus');
const { TaskStore } = require('./taskStore');
const { BudgetLedger } = require('./budgetLedger');
const { WorkerRegistry } = require('./workerRegistry');
const { ContextCompiler } = require('./contextCompiler');
const { TinyLibrarian } = require('./tinyLibrarian');
const { ToolBroker } = require('./toolBroker');
const { HarnessController } = require('./harnessController');
const { AgentConsoleViewProvider } = require('./agentConsoleView');
const { OllamaAdapter } = require('./adapters/ollama');
const { PxProviderGatewayAdapter } = require('./adapters/pxProviderGateway');
const { registerVsCodeReadOnlyTools } = require('./vscodeTools');

const TASK_STATE_KEY = 'pacifyX.agentConsole.taskState.v1';

function registerAgentConsole(vscode, context, options = {}) {
  const disposables = [];
  const eventBus = new CanonicalEventBus();
  const taskStore = new TaskStore({ persistence: { load: () => context.workspaceState.get(TASK_STATE_KEY), save: value => context.workspaceState.update(TASK_STATE_KEY, value) } });
  const hostSettings = options.settingsProvider || (() => ({}));
  const budgetLedger = new BudgetLedger(() => hostSettings().executionPolicy || {}); const workerRegistry = new WorkerRegistry();
  const contextCompiler = new ContextCompiler({ retrievalProvider: options.retrievalProvider || null }); const tinyLibrarian = new TinyLibrarian({ modelRunner: options.tinyModelRunner || null });
  const toolBroker = new ToolBroker({ eventBus, approvalProvider: options.approvalProvider || null });
  const harness = new HarnessController({ eventBus, taskStore, budgetLedger, workerRegistry, contextCompiler, tinyLibrarian, toolBroker, hostSettings });

  if (typeof options.activityObserver === 'function') disposables.push(eventBus.subscribe(event => {
    try { options.activityObserver({ category: 'agent-harness', operation: event.type, status: mapActivityStatus(event.status), effect: 'observe', correlationId: event.runId || event.taskId || event.eventId, taskId: event.taskId || undefined, source: 'px-agent-console', metadata: { event_id: event.eventId, sequence: event.sequence, worker_id: event.workerId, summary_sha256: require('./ids').sha256(event.summary || ''), payload_keys: Object.keys(event.payload || {}).sort().slice(0,40) } }, { attributeClaim: true, listenerId: 'px-agent-console' }); } catch { /* activity authority remains optional during bring-up */ }
  }));

  const settings = hostSettings();
  // Preferred: workers backed by PX's canonical provider gateway.
  for (const descriptor of options.gatewayWorkers || []) {
    if (typeof options.providerGatewayInvoker !== 'function') break;
    const worker = { ...descriptor };
    disposables.push(workerRegistry.register(worker, new PxProviderGatewayAdapter({ worker, invokeProvider: options.providerGatewayInvoker, healthProvider: options.providerGatewayHealth })));
  }
  // Contained bring-up path only. Do not enable this when the canonical PX provider
  // gateway is available for the same local model route.
  if (settings.ollamaEnabled && options.ollamaModel && options.allowDirectOllamaBringup === true) {
    disposables.push(workerRegistry.register({ workerId: `ollama-${safeModelId(options.ollamaModel)}`, adapterId: 'ollama-direct-bringup', providerId: 'ollama-local', modelId: options.ollamaModel, displayName: `Ollama bring-up · ${options.ollamaModel}`,
      costClass: 'local', contextLimit: options.ollamaContextLimit || null, locality: 'local', capabilities: { coding: 0.5, planning: 0.5, review: 0.5, classification: 0.5, toolUse: false, vision: false, structuredOutput: false }, supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 0.5, latencyClass: 'unknown' },
      new OllamaAdapter({ baseUrl: settings.ollamaBaseUrl, model: options.ollamaModel })));
  }

  disposables.push(registerVsCodeReadOnlyTools(vscode, toolBroker, options.workspaceRootProvider));
  const view = new AgentConsoleViewProvider(vscode, context, { harness, openControlPlane: options.openControlPlane, onDiagnostic: options.onDiagnostic });
  disposables.push(vscode.window.registerWebviewViewProvider('pacifyX.agentConsole', view, { webviewOptions: { retainContextWhenHidden: true } }), view);
  disposables.push(vscode.commands.registerCommand('pacifyX.openAgentConsole', () => vscode.commands.executeCommand('pacifyX.agentConsole.focus')));
  disposables.push(vscode.commands.registerCommand('pacifyX.newAgentTask', async () => { const goal = await vscode.window.showInputBox({ title: 'New PX Agent Task', prompt: 'Task goal' }); if (goal) { harness.createTask({ goal, mode: 'ASK', maxEffectClass: 'READ_ONLY', contextBudgetTokens: settings.contextInjectionCapTokens || 12000, taskCostCeilingUsd: settings.executionPolicy?.max_cost_per_task_usd || null, localFirst: settings.executionPolicy?.local_first !== false, requireApprovalBeforeBillable: settings.executionPolicy?.require_approval_before_billable_execution !== false }); await vscode.commands.executeCommand('pacifyX.agentConsole.focus'); } }));
  void workerRegistry.refreshHealth().catch(() => {});

  return { harness, dispose() { harness.dispose(); for (const d of disposables.splice(0)) d?.dispose?.(); } };
}

function safeModelId(value) { return String(value || 'model').toLowerCase().replace(/[^a-z0-9._:-]+/g, '-').slice(0, 100) || 'model'; }
function mapActivityStatus(value) { return value === 'succeeded' ? 'succeeded' : value === 'failed' ? 'failed' : value === 'cancelled' ? 'cancelled' : value === 'started' ? 'started' : 'progress'; }

module.exports = { registerAgentConsole, TASK_STATE_KEY };
