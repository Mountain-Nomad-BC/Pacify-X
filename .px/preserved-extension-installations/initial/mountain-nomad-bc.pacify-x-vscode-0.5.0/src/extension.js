'use strict';

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { findEngineRoot, runValidation, isPathWithin } = require('./runtimeBridge');
const { PxBridge, disconnected } = require('./pxBridge');
const { ControlCenterTreeProvider } = require('./treeProvider');
const { buildContextEnvelope, providerStatus, gitConflictDecision, CodexRunManager } = require('./contextBridge');
const { OllamaChatProvider } = require('./ollamaProvider');
const { scanCleanupCandidates, executeCleanup } = require('./cleanupManager');
const { inventoryTeamPack, stageTeamPack, workerAdapters } = require('./teamFabricManager');
const { initializeEnterprise, setPackEnabled, configureTarget, setExecutionPolicy, enterpriseDoctor } = require('./enterpriseManager');
const { discoverEnvironment, readEnvironmentInventory, readEnvironmentSubject, readEnvironmentExtension, pathsFor: environmentPathsFor } = require('./discoveryManager');
const { recordActivity, readActivity, sha: activityHash } = require('./activityManager');
const {
  registerSession, readCoordination, createParallelPlan, claimTask, renewClaim, recordProgress,
  reconcileTask, releaseTask, captureMemory, readMemoryTelemetry, taskHandoff
} = require('./coordinationManager');

let panel;
let refreshTimer;
let currentSnapshot;
let currentContextEnvelope;
let currentEnvironment;
let activeRuntime;

function settings() {
  const config = vscode.workspace.getConfiguration('pacifyX');
  const providerAllowlist = config.get('guardrails.providerAllowlist');
  return {
    showAdvancedSurfaces: Boolean(config.get('showAdvancedSurfaces')),
    glassIntensity: Number(config.get('glassIntensity') || 0.66),
    refreshIntervalSeconds: Number(config.get('refreshIntervalSeconds') || 20),
    contextInjectionCapTokens: Number(config.get('contextInjectionCapTokens') || 12000),
    codexSandbox: String(config.get('codexSandbox') || 'read-only'),
    ollamaEnabled: Boolean(config.get('ollama.enabled')),
    ollamaBaseUrl: String(config.get('ollama.baseUrl') || 'http://127.0.0.1:11434'),
    pythonPath: String(config.get('pythonPath') || 'python'),
    workspaceRoot: String(config.get('workspaceRoot') || '').trim(),
    activity: {
      enabled: config.get('activity.enabled') !== false,
      paused: Boolean(config.get('activity.paused')),
      captureFileEvents: config.get('activity.captureFileEvents') !== false,
      captureTerminalLifecycle: config.get('activity.captureTerminalLifecycle') !== false,
      captureTaskLifecycle: config.get('activity.captureTaskLifecycle') !== false,
      captureDebugLifecycle: config.get('activity.captureDebugLifecycle') !== false,
      captureTestLifecycle: config.get('activity.captureTestLifecycle') !== false,
      captureMcpCalls: config.get('activity.captureMcpCalls') !== false,
      captureCommandText: Boolean(config.get('activity.captureCommandText')),
      retentionDays: Number(config.get('activity.retentionDays') || 30)
    },
    executionPolicy: {
      master_enabled: Boolean(config.get('billable.enabled')),
      max_cost_per_task_usd: Number(config.get('guardrails.maxCostPerTaskUsd') || 0),
      max_cost_per_session_usd: Number(config.get('guardrails.maxCostPerSessionUsd') || 0),
      max_cost_per_day_usd: Number(config.get('guardrails.maxCostPerDayUsd') || 0),
      token_budget: Number(config.get('guardrails.tokenBudget') ?? 12000),
      local_first: config.get('guardrails.localFirst') !== false,
      provider_allowlist: Array.isArray(providerAllowlist) ? providerAllowlist.map(String) : [],
      gpu_memory_ceiling_mb: Number(config.get('guardrails.gpuMemoryCeilingMb') || 0),
      cpu_core_ceiling: Number(config.get('guardrails.cpuCoreCeiling') || 4),
      ram_ceiling_mb: Number(config.get('guardrails.ramCeilingMb') || 8192),
      escalation_confidence_threshold: Number(config.get('guardrails.escalationConfidenceThreshold') ?? 0.85),
      cache_reuse_aggressiveness: String(config.get('guardrails.cacheReuseAggressiveness') || 'balanced'),
      require_approval_before_billable_execution: config.get('guardrails.requireApprovalBeforeBillableExecution') !== false
    }
  };
}

function workspaceRoot() {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || engineRoot();
}

function engineRoot() {
  const configured = String(vscode.workspace.getConfiguration('pacifyX').get('engineRoot') || '').trim();
  return findEngineRoot(configured, (vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath));
}

function actorIdentity(sessionId = activeRuntime?.sessionId || 'extension-session') {
  const fingerprint = crypto.createHash('sha256').update(`${String(vscode.env.machineId || 'local-machine')}:${String(vscode.env.appName || 'vscode-host')}`).digest('hex').slice(0, 16);
  return {
    actorId: `ide-${fingerprint}`, sessionId, harness: vscode.env.appName || 'VS Code compatible host',
    accountableOwner: 'local-user'
  };
}

function portableContextSnapshot() {
  const editor = vscode.window.activeTextEditor;
  const workspace = vscode.workspace.workspaceFolders?.[0];
  const activeFile = editor?.document?.uri?.scheme === 'file' ? editor.document.uri.fsPath : undefined;
  const relativeFile = activeFile && workspace ? path.relative(workspace.uri.fsPath, activeFile) : undefined;
  const config = settings();
  return {
    schema_version: '2.0', created_utc: new Date().toISOString(),
    handoff: {
      correlation_id: crypto.randomUUID(), task_id: null,
      source: { surface: vscode.env.appName || 'VS Code', provider: 'Pacify-X extension', session_id: activeRuntime?.sessionId || null },
      context: {
        workspace_id: workspace?.name || null, repository: workspace?.uri?.fsPath || null,
        branch: currentSnapshot?.project?.branch || null, commit: currentSnapshot?.source?.commit || null,
        selected_files: relativeFile ? [relativeFile] : [], selection: null, selection_content_included: false,
        instruction_refs: ['AGENTS.md'], memory_refs: currentSnapshot?.coordinationData?.paths ? [
          path.relative(workspace.uri.fsPath, currentSnapshot.coordinationData.paths.handoff_json).replaceAll('\\', '/')
        ] : [], tool_result_refs: currentSnapshot?.environmentPaths?.current ? [currentSnapshot.environmentPaths.current] : [], declared_context_cap_tokens: config.contextInjectionCapTokens
      },
      target: { executor: null, provider: null, authentication_identity: null, billing_identity: null, model: null, session_id: null }
    },
    guarantees: { credentials_included: false, billing_identity_inferred: false, canonical_memory_mutated: false, native_session_transfer: false }
  };
}

async function liveContextEnvelope(objective = '', coordinationData = currentSnapshot?.coordinationData) {
  const workspace = vscode.workspace.workspaceFolders?.[0];
  const root = workspace?.uri?.fsPath || engineRoot();
  const activeFile = vscode.window.activeTextEditor?.document?.uri?.scheme === 'file' ? vscode.window.activeTextEditor.document.uri.fsPath : undefined;
  const openFiles = vscode.workspace.textDocuments.filter(document => document.uri.scheme === 'file').map(document => document.uri.fsPath);
  const provider = await providerStatus(root);
  const envelope = buildContextEnvelope({
    objective, workspaceRoot: root, engineRoot: engineRoot(), activeFile, openFiles,
    contextCapTokens: settings().contextInjectionCapTokens, sandbox: settings().codexSandbox,
    authenticationIdentity: provider.authenticationIdentity, coordination: coordinationData,
    sourceSurface: vscode.env.appName || 'VS Code', sourceSessionId: activeRuntime?.sessionId || null
  });
  envelope.environment_capability_map = currentEnvironment?.inventory ? {
    schema_version: currentEnvironment.inventory.schema_version, snapshot_hash: currentEnvironment.inventory.snapshot_hash,
    path: currentEnvironment.paths.current, summary: currentEnvironment.inventory.summary
  } : null;
  return envelope;
}

async function openContextSnapshot() {
  const snapshot = currentContextEnvelope || await liveContextEnvelope();
  const document = await vscode.workspace.openTextDocument({ language: 'json', content: `${JSON.stringify(snapshot, null, 2)}\n` });
  await vscode.window.showTextDocument(document, { preview: true });
}

function getHtml(webview, extensionPath) {
  const media = name => webview.asWebviewUri(vscode.Uri.file(path.join(extensionPath, 'media', name)));
  const nonce = crypto.randomBytes(18).toString('base64');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource}; script-src 'nonce-${nonce}'; font-src ${webview.cspSource};">
  <link rel="stylesheet" href="${media('dashboard.css')}">
  <title>Pacify-X Control Plane</title>
</head>
<body>
  <div id="app" data-shield-uri="${media('px-shield-256.png')}" data-brand-uri="${media('px-shield-128.png')}" aria-live="polite"></div>
  <script nonce="${nonce}" src="${media('dashboard.js')}"></script>
</body>
</html>`;
}

function activate(context) {
  const tree = new ControlCenterTreeProvider(vscode);
  const codexRuns = new CodexRunManager();
  const codexOutput = vscode.window.createOutputChannel('Pacify-X Codex Bridge');
  const contextDirectory = path.join(context.globalStorageUri.fsPath, 'context-cache');
  const contextPath = path.join(contextDirectory, 'current.json');
  const cleanupReceiptDirectory = path.join(context.globalStorageUri.fsPath, 'cleanup-receipts');
  const sessionId = `session-${crypto.randomUUID()}`;
  activeRuntime = { sessionId, lastHeartbeat: 0 };
  let cleanupInventory;
  let publishPromise;
  let discoveryPromise;
  let activityPublishTimer;
  const editAggregates = new Map();
  const watcherTimers = new Map();
  const terminalCorrelations = new WeakMap();
  const shellCorrelations = new WeakMap();
  const taskCorrelations = new WeakMap();
  const debugCorrelations = new Map();
  fs.mkdirSync(contextDirectory, { recursive: true });
  context.subscriptions.push(vscode.window.registerTreeDataProvider('pacifyX.controlCenter', tree), codexOutput, { dispose: () => codexRuns.cancel() });

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 35);
  status.command = 'pacifyX.openDashboard'; status.text = '$(shield) PX · idle'; status.tooltip = 'Open Pacify-X Control Plane'; status.show();
  context.subscriptions.push(status);

  function bridge() {
    if (!activeRuntime.bridge) activeRuntime.bridge = new PxBridge({});
    activeRuntime.bridge.update({
      pythonPath: settings().pythonPath, engineRoot: engineRoot(), projectRoot: workspaceRoot(),
      workspaceRoot: settings().workspaceRoot || undefined
    });
    return activeRuntime.bridge;
  }

  function coordination() {
    const root = workspaceRoot();
    if (!root) return null;
    const data = readCoordination(root, { eventLimit: 50 });
    data.activity = readActivity(root, { limit: 120, policy: settings().activity });
    return data;
  }

  function currentClaim(actor = actorIdentity(sessionId)) {
    const claims = currentSnapshot?.coordinationData?.state?.claims || [];
    return claims.find(item => item.status === 'active' && item.actor?.actor_id === actor.actorId && item.actor?.session_id === actor.sessionId) || null;
  }

  function publishActivitySoon() {
    clearTimeout(activityPublishTimer);
    activityPublishTimer = setTimeout(() => {
      const root = workspaceRoot(); if (!root) return;
      const activity = readActivity(root, { limit: 120, policy: settings().activity });
      if (currentSnapshot?.coordinationData) currentSnapshot.coordinationData.activity = activity;
      void panel?.webview.postMessage({ type: 'activityResult', result: activity });
    }, 180);
  }

  function observeActivity(input, options = {}) {
    const root = workspaceRoot(); if (!root) return { recorded: false, reason: 'workspace-unavailable' };
    const actor = options.actor || actorIdentity(sessionId); const claim = options.attributeClaim === false ? null : currentClaim(actor);
    try {
      const result = recordActivity(root, actor, {
        ...input, taskId: input.taskId || claim?.task_id || null, claimId: input.claimId || claim?.id || null
      }, settings().activity);
      if (result.recorded) publishActivitySoon();
      return result;
    } catch (error) {
      codexOutput.appendLine(`Activity observation failed closed: ${error.message}`);
      return { recorded: false, reason: error.message };
    }
  }

  function relativeScope(uri) {
    if (!uri?.fsPath) return null; const root = workspaceRoot(); if (!root) return null;
    const relative = path.relative(root, uri.fsPath); return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative)) ? relative.replaceAll('\\', '/') || '.' : null;
  }

  function excludedActivityPath(uri) {
    const relative = relativeScope(uri); if (!relative) return true;
    return /(^|\/)(\.git|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.playwright-profile[^/]*|\.edge-profile[^/]*|\.chrome-profile[^/]*)(\/|$)/i.test(relative)
      || /^\.engineering-bootstrap\/coordination\/activity(\/|$)/i.test(relative);
  }

  function unknownObserver(source) {
    return { actorId: `${source}-unattributed`, sessionId: 'external-or-unknown', harness: source, accountableOwner: 'unknown' };
  }

  function enterprise() {
    const root = workspaceRoot();
    if (!root || !currentSnapshot?.enterprise?.catalog_id) return null;
    return initializeEnterprise(root, currentSnapshot.enterprise);
  }

  try { if (workspaceRoot()) { registerSession(workspaceRoot(), actorIdentity(sessionId)); activeRuntime.lastHeartbeat = Date.now(); } } catch (error) {
    codexOutput.appendLine(`Coordination initialization failed closed: ${error.message}`);
  }
  observeActivity({ category: 'agent', operation: 'agent.session', status: 'started', source: 'vscode-extension', effect: 'observe', correlationId: sessionId, metadata: { extension_version: context.extension.packageJSON?.version || null, app_name: vscode.env.appName } });
  context.subscriptions.push({ dispose: () => {
    try { observeActivity({ category: 'agent', operation: 'agent.session', status: 'idle', source: 'vscode-extension', effect: 'observe', correlationId: sessionId }); } catch {}
    clearTimeout(activityPublishTimer); for (const aggregate of editAggregates.values()) clearTimeout(aggregate.timer); for (const timer of watcherTimers.values()) clearTimeout(timer);
  } });

  async function publishCoordination() {
    const data = coordination();
    if (currentSnapshot) {
      currentSnapshot.coordinationData = data;
      currentSnapshot.coordination = data?.state || { instrumented: false };
    }
    await panel?.webview.postMessage({ type: 'coordination', coordination: data });
    return data;
  }

  async function refreshEnvironment(reason = 'manual-refresh', notify = true) {
    if (discoveryPromise) return discoveryPromise;
    const root = workspaceRoot();
    if (!root) throw new Error('Open a workspace before refreshing the environment capability map.');
    discoveryPromise = discoverEnvironment({ extensions: vscode.extensions.all, projectRoot: root, pythonPath: settings().pythonPath, reason })
      .then(async result => {
        currentEnvironment = result;
        if (currentSnapshot) { currentSnapshot.environment = result.inventory; currentSnapshot.environmentPaths = result.paths; }
        await panel?.webview.postMessage({ type: 'environmentInventory', result });
        if (notify) await vscode.window.showInformationMessage(`Pacify-X mapped ${result.inventory.summary.graph_nodes} environment nodes and ${result.inventory.summary.graph_edges} semantic relations.`);
        return result;
      }).finally(() => { discoveryPromise = null; });
    return discoveryPromise;
  }

  async function publishSnapshot(force = false) {
    if (publishPromise) return publishPromise;
    publishPromise = (async () => {
      status.text = '$(sync~spin) PX · reading canonical state';
      try {
        currentSnapshot = await bridge().snapshot({ force });
      } catch (error) {
        currentSnapshot = disconnected(error instanceof Error ? error.message : String(error));
      }
      const root = workspaceRoot();
      if (root && Date.now() - activeRuntime.lastHeartbeat > 5 * 60_000) {
        try { registerSession(root, actorIdentity(sessionId)); activeRuntime.lastHeartbeat = Date.now(); } catch (error) { codexOutput.appendLine(`Coordination heartbeat failed closed: ${error.message}`); }
      }
      const coordinationData = root ? coordination() : null;
      const [provider, envelope] = await Promise.all([providerStatus(root), liveContextEnvelope('', coordinationData)]);
      currentContextEnvelope = envelope;
      currentSnapshot.provider = provider; currentSnapshot.git = envelope.git;
      currentSnapshot.teamFabric = {
        sourcePack: 'PX Team Fabric Ecosystem Integration Pack v0.2.0',
        adapters: workerAdapters({
          workspaceRoot: root, extensionRoot: context.extensionPath, appName: vscode.env.appName,
          codexAuthenticated: /ChatGPT \(verified by Codex CLI\)/i.test(String(provider.authenticationIdentity || '')),
          ollamaEnabled: settings().ollamaEnabled
        })
      };
      const enterpriseData = currentSnapshot.enterprise?.catalog_id ? initializeEnterprise(root, currentSnapshot.enterprise) : null;
      currentSnapshot.enterpriseState = enterpriseData?.state || null;
      currentSnapshot.enterprisePaths = enterpriseData?.paths || null;
      currentEnvironment = currentEnvironment || (root ? readEnvironmentInventory(root) : null);
      currentSnapshot.environment = currentEnvironment?.inventory || null;
      currentSnapshot.environmentPaths = currentEnvironment?.paths || (root ? environmentPathsFor(root) : null);
      currentSnapshot.coordinationData = coordinationData;
      currentSnapshot.coordination = coordinationData?.state || currentSnapshot.coordination || { instrumented: false };
      currentSnapshot.bridge = { active: codexRuns.isActive(), decision: gitConflictDecision(envelope.git, codexRuns.isActive()), contextPath, authoritativeContext: coordinationData?.paths?.handoff_json || null };
      const validationKey = `validation:${crypto.createHash('sha256').update(`${currentSnapshot.source?.engineRoot || ''}:${currentSnapshot.source?.commit || ''}`).digest('hex')}`;
      currentSnapshot.validation = context.globalState.get(validationKey) || currentSnapshot.validation;
      if (envelope.git.dirty) currentSnapshot.attention.push({
        severity: 'info', title: 'Working tree changes observed',
        detail: `${envelope.git.staged || 0} staged, ${envelope.git.unstaged || 0} unstaged, ${envelope.git.untracked || 0} untracked; Git remains authoritative.`
      });
      fs.writeFileSync(contextPath, `${JSON.stringify({ cache: true, authoritative_handoff: coordinationData?.paths?.handoff_json || null, envelope }, null, 2)}\n`, 'utf8');
      tree.setSnapshot(currentSnapshot);
      status.text = currentSnapshot.connected ? (currentSnapshot.attention.length ? `$(warning) PX · ${currentSnapshot.attention.length} attention` : '$(shield) PX · ready') : '$(warning) PX · disconnected';
      await panel?.webview.postMessage({ type: 'snapshot', snapshot: currentSnapshot, settings: settings(), coordination: coordinationData, clientActor: actorIdentity(sessionId) });
      return currentSnapshot;
    })().finally(() => { publishPromise = null; });
    return publishPromise;
  }

  async function validateControlPlane() {
    status.text = '$(loading~spin) PX · validating';
    const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Pacify-X control-plane validation', cancellable: false }, () => runValidation({
      pythonPath: settings().pythonPath, engineRoot: engineRoot()
    }));
    if (currentSnapshot) {
      currentSnapshot.validation = result;
      const validationKey = `validation:${crypto.createHash('sha256').update(`${currentSnapshot.source?.engineRoot || ''}:${currentSnapshot.source?.commit || ''}`).digest('hex')}`;
      await context.globalState.update(validationKey, result);
    }
    tree.setSnapshot(currentSnapshot); await panel?.webview.postMessage({ type: 'validation', result });
    status.text = result.status === 'passed' ? '$(pass-filled) PX · validated' : '$(error) PX · validation failed';
    const action = await vscode.window.showInformationMessage(`Pacify-X validation: ${result.status}. ${result.detail}`, 'Show output');
    if (action === 'Show output') { const channel = vscode.window.createOutputChannel('Pacify-X Validation'); channel.appendLine(result.output || result.detail); channel.show(true); context.subscriptions.push(channel); }
    return result;
  }

  async function publishCleanupCandidates() {
    const root = engineRoot();
    if (!root) { await panel?.webview.postMessage({ type: 'cleanupError', error: 'Configure or open a Pacify-X engine root before scanning cleanup candidates.' }); return; }
    try {
      cleanupInventory = await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title: 'Pacify-X: classifying safe cleanup candidates' }, () => scanCleanupCandidates(root));
      await panel?.webview.postMessage({ type: 'cleanupCandidates', inventory: {
        summary: cleanupInventory.summary, orchestration: cleanupInventory.orchestration,
        candidates: cleanupInventory.candidates.map(({ path: _hostOnlyPath, ...candidate }) => candidate)
      } });
    } catch (error) { cleanupInventory = undefined; await panel?.webview.postMessage({ type: 'cleanupError', error: error instanceof Error ? error.message : String(error) }); }
  }

  async function performCleanup(message) {
    const ids = Array.isArray(message.ids) ? message.ids.map(String) : [];
    const disposition = message.disposition === 'permanent' ? 'permanent' : 'recycle';
    const currentRoot = engineRoot();
    if (!cleanupInventory || cleanupInventory.root !== path.resolve(currentRoot || '') || !ids.length) {
      await vscode.window.showWarningMessage('Pacify-X cleanup selection is stale or empty. Scan again before cleanup.'); await publishCleanupCandidates(); return;
    }
    const actionLabel = disposition === 'permanent' ? 'Permanently Delete' : 'Move to Recycle Bin';
    const approved = await vscode.window.showWarningMessage(`${actionLabel} ${ids.length} selected cleanup candidate${ids.length === 1 ? '' : 's'}?`, {
      modal: true, detail: disposition === 'permanent' ? 'Permanent deletion cannot be undone. Every selected generated cache is re-inventoried and hash-compared immediately before disposition.' : 'Selected generated caches will be moved to the operating-system Recycle Bin.'
    }, actionLabel);
    if (approved !== actionLabel) return;
    try {
      const result = await executeCleanup({
        root: cleanupInventory.root, candidates: cleanupInventory.candidates, ids, disposition, receiptDir: cleanupReceiptDirectory,
        deletePath: (target, options) => vscode.workspace.fs.delete(vscode.Uri.file(target), options)
      });
      await panel?.webview.postMessage({ type: 'cleanupResult', result });
      const failed = result.receipt.errors.length;
      const messageText = failed ? `Pacify-X cleanup completed with ${failed} failure(s); inspect the retained receipt.` : `Pacify-X cleanup completed: ${result.receipt.resources_reclaimed} reclaimed; receipt retained.`;
      if (failed) await vscode.window.showWarningMessage(messageText); else await vscode.window.showInformationMessage(messageText);
      await publishSnapshot(true); await publishCleanupCandidates();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      await panel?.webview.postMessage({ type: 'cleanupError', error: detail }); await vscode.window.showErrorMessage(`Pacify-X cleanup failed closed: ${detail}`);
    }
  }

  async function previewTeamPack() {
    const selection = await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true, canSelectMany: false, title: 'Select an Agent Companies / Team Fabric package to audit' });
    if (!selection?.[0]) return;
    const skillIds = []; let offset = 0;
    while (true) {
      const page = await bridge().catalog({ kind: 'skills', offset, limit: 100, sort: 'id' });
      skillIds.push(...page.items.map(item => item.id));
      if (!page.has_more) break;
      offset += page.limit;
    }
    const preview = inventoryTeamPack(selection[0].fsPath, skillIds);
    await panel?.webview.postMessage({ type: 'teamPackResult', phase: 'preview', result: preview });
    if (!preview.entities.length) return vscode.window.showInformationMessage('Pacify-X found no Agent Companies entities to stage.');
    const collisionMode = await vscode.window.showQuickPick([
      { label: 'Skip collisions', value: 'skip', description: 'Stage only new candidate identities.' },
      { label: 'Rename collisions', value: 'rename', description: 'Stage colliding identities with a hash suffix.' },
      { label: 'Replace candidate only', value: 'replace-candidate-only', description: 'Replace only a prior staged candidate; never canonical content.' }
    ], { title: 'Team package collision policy', placeHolder: 'Choose a fail-closed staging policy' });
    if (!collisionMode) return;
    const approved = await vscode.window.showWarningMessage(`Stage ${preview.entities.length} package entities as non-canonical candidates?`, { modal: true, detail: 'This writes a provenance receipt under the project coordination ledger. It does not alter canonical agents, skills, projects, or tasks.' }, 'Stage candidates');
    if (approved !== 'Stage candidates') return;
    const staged = stageTeamPack(workspaceRoot(), preview, { collisionMode: collisionMode.value });
    await panel?.webview.postMessage({ type: 'teamPackResult', phase: 'staged', result: staged });
    await vscode.window.showInformationMessage(`Pacify-X staged ${staged.receipt.staged_count} Team Fabric candidate(s); canonical admission remains pending.`);
    await publishSnapshot(true);
  }

  async function enterpriseAction(message) {
    const root = workspaceRoot();
    if (!root || !currentSnapshot?.enterprise?.catalog_id) throw new Error('The separate MS+Enterprise catalog is unavailable.');
    const catalog = currentSnapshot.enterprise;
    let result;
    if (message.type === 'enterprisePackToggle') {
      const pack = catalog.packs.find(item => item.id === message.packId);
      if (!pack) throw new Error('Unknown MS+Enterprise pack.');
      const enabled = Boolean(message.enabled);
      const label = enabled ? 'Enable offline metadata' : 'Disable pack metadata';
      const approved = await vscode.window.showWarningMessage(`${label} for ${pack.name}?`, { modal: true, detail: 'This only changes the separate project enterprise state. It does not connect to Microsoft, read credentials, enable network egress, authorize tenant mutation, or enable billable services.' }, label);
      if (approved !== label) return;
      result = setPackEnabled(root, catalog, { packId: pack.id, enabled });
    } else if (message.type === 'enterpriseTargetConfigure') {
      const pack = catalog.packs.find(item => item.id === message.packId);
      if (!pack) throw new Error('Unknown MS+Enterprise pack.');
      const targetAlias = await vscode.window.showInputBox({ title: `Configure ${pack.name}`, prompt: 'Local target label (no credentials or secrets)', placeHolder: 'Development tenant target', ignoreFocusOut: true });
      if (!targetAlias) return;
      const tenantAlias = await vscode.window.showInputBox({ title: `Configure ${pack.name}`, prompt: 'Tenant alias only (no tenant secret)', placeHolder: 'contoso-dev', ignoreFocusOut: true });
      if (!tenantAlias) return;
      const environmentAlias = await vscode.window.showInputBox({ title: `Configure ${pack.name}`, prompt: 'Environment/subscription alias only', placeHolder: 'sandbox', ignoreFocusOut: true });
      if (!environmentAlias) return;
      result = configureTarget(root, catalog, { id: `target-${crypto.randomUUID()}`, packId: pack.id, targetAlias, tenantAlias, environmentAlias });
    } else if (message.type === 'enterpriseDoctor') result = enterpriseDoctor(root, catalog);
    else if (message.type === 'toggleBillablePolicy') {
      const enabled = Boolean(message.enabled);
      if (enabled) {
        const approved = await vscode.window.showWarningMessage('Enable the billable-provider policy master?', { modal: true, detail: 'This does not create or read credentials, contact a provider, or spend money. Every future billable execution must still pass provider, cost, token, hardware, confidence, local-first, and approval gates.' }, 'Enable guarded policy');
        if (approved !== 'Enable guarded policy') return;
      }
      await vscode.workspace.getConfiguration('pacifyX').update('billable.enabled', enabled, vscode.ConfigurationTarget.Workspace);
      result = setExecutionPolicy(root, catalog, { ...settings().executionPolicy, master_enabled: enabled });
    }
    else throw new Error('Unsupported MS+Enterprise action.');
    await publishSnapshot(true);
    await panel?.webview.postMessage({ type: 'enterpriseResult', operation: message.type, result });
    return result;
  }

  async function continueWithCodex() {
    if (codexRuns.isActive()) return vscode.window.showWarningMessage('A Pacify-X bridge-owned Codex run is already active.');
    const root = workspaceRoot(); const actor = actorIdentity(sessionId); const coordinationData = root ? coordination() : null;
    const ownedTask = coordinationData?.state?.tasks?.find(task => task.owner?.actor_id === actor.actorId && ['claimed', 'in_progress', 'waiting'].includes(task.status));
    const objective = await vscode.window.showInputBox({ prompt: 'What should Codex continue with?', value: ownedTask?.title || '', placeHolder: 'Describe the bounded task for this workspace', ignoreFocusOut: true });
    if (!objective?.trim()) return;
    const envelope = await liveContextEnvelope(objective.trim(), coordinationData);
    envelope.coordination_task = ownedTask || null;
    if (!/ChatGPT \(verified by Codex CLI\)/i.test(String(envelope.target.authentication_identity || ''))) return vscode.window.showErrorMessage('Pacify-X blocked Codex: a verified ChatGPT login is required and billable API credentials are never used as fallback.');
    const decision = gitConflictDecision(envelope.git, false);
    if (!decision.allowed) return vscode.window.showErrorMessage(`Pacify-X blocked the Codex handoff: ${decision.reasons.join(', ')}. Resolve the Git operation/conflicts first.`);
    const sandbox = settings().codexSandbox === 'workspace-write' ? 'workspace-write' : 'read-only';
    if (sandbox === 'workspace-write' && !ownedTask) return vscode.window.showErrorMessage('Pacify-X blocked workspace-write: claim a dependency-ready Parallel Plan task and its file/area scope first.');
    if (sandbox === 'workspace-write') {
      const approved = await vscode.window.showWarningMessage(`Allow one Codex workspace-write run for claimed task ${ownedTask.id}? Git mutations remain prohibited.`, { modal: true }, 'Run claimed task');
      if (approved !== 'Run claimed task') return;
    }
    currentContextEnvelope = envelope; fs.writeFileSync(contextPath, `${JSON.stringify({ cache: true, authoritative_handoff: coordinationData?.paths?.handoff_json, envelope }, null, 2)}\n`, 'utf8');
    if (root) captureMemory(root, actor, { layer: 'session', kind: 'task-objective', content: objective.trim(), sourceArtifact: coordinationData?.paths?.handoff_json || 'extension-input' });
    const runStarted = Date.now();
    observeActivity({ category: 'agent', operation: 'agent.codex.run', status: 'started', source: 'pacify-codex-bridge', effect: sandbox === 'workspace-write' ? 'workspace-write' : 'workspace-read', correlationId: envelope.correlation_id, inputSha256: activityHash(objective.trim()), scopeRefs: [envelope.context.workspace], metadata: { sandbox, objective_sha256: activityHash(objective.trim()), objective_length: objective.trim().length, bridge_owned: true } });
    codexOutput.clear(); codexOutput.appendLine(`Pacify-X context ${envelope.correlation_id}`); codexOutput.appendLine(`Sandbox: ${sandbox}; Git mutation authority: denied`); codexOutput.show(true);
    status.text = '$(loading~spin) PX · Codex running';
    try {
      const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Pacify-X governed Codex handoff', cancellable: true }, async (_progress, token) => {
        const cancellation = token.onCancellationRequested(() => codexRuns.cancel());
        try { return await codexRuns.run({ envelope, cwd: envelope.context.workspace, sandbox, onEvent: event => {
          codexOutput.appendLine(JSON.stringify(event));
          observeActivity({ category: 'agent', operation: `agent.codex.${String(event?.type || 'event').replace(/[^a-z0-9._-]+/gi, '-').toLowerCase()}`, status: 'observed', source: 'pacify-codex-bridge', effect: 'observe', correlationId: envelope.correlation_id, outputSha256: activityHash(JSON.stringify(event ?? null)), metadata: { event_type: event?.type || null, item_type: event?.item?.type || null, item_id: event?.item?.id || null, status: event?.status || null, usage: event?.usage || null, content: '[redacted]' } });
        } }); }
        finally { cancellation.dispose(); }
      });
      codexOutput.appendLine(`Run closed: exit=${result.code} cancelled=${result.cancelled}`);
      observeActivity({ category: 'agent', operation: 'agent.codex.run', status: result.cancelled ? 'cancelled' : result.code === 0 ? 'succeeded' : 'failed', source: 'pacify-codex-bridge', effect: sandbox === 'workspace-write' ? 'workspace-write' : 'workspace-read', correlationId: envelope.correlation_id, durationMs: Date.now() - runStarted, metadata: { exit_code: result.code, cancelled: result.cancelled, timed_out: result.timedOut, bridge_owned: true } });
      if (root && ownedTask) recordProgress(root, actor, { taskId: ownedTask.id, status: 'waiting', summary: `Codex run closed with exit ${result.code}; human/agent review and reconciliation required.`, nextAction: 'Review changes, run acceptance checks, then mark complete and reconcile.' });
      status.text = result.code === 0 ? '$(pass-filled) PX · Codex awaiting review' : '$(error) PX · Codex stopped';
    } catch (error) {
      observeActivity({ category: 'agent', operation: 'agent.codex.run', status: 'failed', source: 'pacify-codex-bridge', effect: sandbox === 'workspace-write' ? 'workspace-write' : 'workspace-read', correlationId: envelope.correlation_id, durationMs: Date.now() - runStarted, metadata: { failure_code: error.code || 'bridge-error', error_sha256: activityHash(error.message || String(error)) } });
      status.text = '$(error) PX · Codex failed'; codexOutput.appendLine(`Run failed: ${error.message}`); await vscode.window.showErrorMessage(`Pacify-X Codex bridge failed: ${error.message}`);
    }
    await publishSnapshot(true);
  }

  async function coordinationAction(message) {
    const root = workspaceRoot(); if (!root) throw new Error('Open a workspace before using coordination.');
    const actor = actorIdentity(sessionId);
    let result;
    if (message.type === 'createParallelPlan') result = createParallelPlan(root, actor, message.plan || {});
    else if (message.type === 'claimCoordinationTask') result = claimTask(root, actor, { taskId: message.taskId, claimTargets: message.claimTargets, ttlMinutes: message.ttlMinutes, mode: message.mode, authority: message.authority });
    else if (message.type === 'renewCoordinationClaim') {
      const snapshot = coordination(); const claim = snapshot?.state?.claims?.find(item => item.id === message.claimId);
      result = renewClaim(root, actor, { claimId: message.claimId, fencingTokens: claim?.fencing_tokens || {}, ttlMinutes: message.ttlMinutes });
    }
    else if (message.type === 'recordTaskProgress') {
      const snapshot = coordination();
      const claim = snapshot?.state?.claims?.find(item => item.task_id === message.taskId && item.actor?.actor_id === actor.actorId && item.actor?.session_id === actor.sessionId);
      result = recordProgress(root, actor, { ...message, fencingTokens: claim?.fencing_tokens || {} });
    }
    else if (message.type === 'reconcileCoordinationTask') result = reconcileTask(root, actor, message);
    else if (message.type === 'releaseCoordinationTask') result = releaseTask(root, actor, message);
    else if (message.type === 'captureCoordinationMemory') result = captureMemory(root, actor, message);
    else throw new Error('Unsupported coordination action.');
    await publishCoordination(); await panel?.webview.postMessage({ type: 'coordinationResult', result });
    return result;
  }

  function registerActivityHooks() {
    const subscriptions = [];
    const observeDocument = (operation, document, status = 'observed', metadata = {}) => {
      if (!settings().activity.captureFileEvents || document?.uri?.scheme !== 'file' || excludedActivityPath(document.uri)) return;
      observeActivity({ category: 'editor', operation, status, source: 'vscode-editor', effect: 'workspace-read', scopeRefs: [document.uri.fsPath], metadata: { language_id: document.languageId, version: document.version, ...metadata } });
    };
    const flushEdit = key => {
      const aggregate = editAggregates.get(key); if (!aggregate) return; editAggregates.delete(key); clearTimeout(aggregate.timer);
      observeDocument('editor.document.changed', aggregate.document, 'observed', { change_batches: aggregate.batches, changed_regions: aggregate.regions, inserted_bytes: aggregate.insertedBytes, deleted_units: aggregate.deletedUnits, first_change_utc: aggregate.firstChangeUtc });
    };
    subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => {
      if (!settings().activity.captureFileEvents || event.document.uri.scheme !== 'file' || excludedActivityPath(event.document.uri) || !event.contentChanges.length) return;
      const key = event.document.uri.toString(); const existing = editAggregates.get(key) || { document: event.document, batches: 0, regions: 0, insertedBytes: 0, deletedUnits: 0, firstChangeUtc: new Date().toISOString(), timer: null };
      existing.document = event.document; existing.batches += 1; existing.regions += event.contentChanges.length;
      for (const change of event.contentChanges) { existing.insertedBytes += Buffer.byteLength(change.text || '', 'utf8'); existing.deletedUnits += Number(change.rangeLength || 0); }
      clearTimeout(existing.timer); existing.timer = setTimeout(() => flushEdit(key), 900); editAggregates.set(key, existing);
    }));
    subscriptions.push(vscode.workspace.onDidSaveTextDocument(document => {
      flushEdit(document.uri.toString());
      if (!settings().activity.captureFileEvents || document.uri.scheme !== 'file' || excludedActivityPath(document.uri)) return;
      const content = document.getText(); observeDocument('editor.document.saved', document, 'succeeded', { bytes: Buffer.byteLength(content, 'utf8'), content_sha256: activityHash(content) });
    }));
    subscriptions.push(vscode.workspace.onDidOpenTextDocument(document => observeDocument('editor.document.opened', document)));
    subscriptions.push(vscode.workspace.onDidCloseTextDocument(document => { flushEdit(document.uri.toString()); observeDocument('editor.document.closed', document, 'idle'); }));
    if (vscode.workspace.onDidCreateFiles) subscriptions.push(vscode.workspace.onDidCreateFiles(event => {
      for (const uri of event.files) if (!excludedActivityPath(uri)) observeActivity({ category: 'filesystem', operation: 'workspace.file.created', status: 'observed', source: 'vscode-workspace', effect: 'workspace-write', scopeRefs: [uri.fsPath] });
    }));
    if (vscode.workspace.onDidDeleteFiles) subscriptions.push(vscode.workspace.onDidDeleteFiles(event => {
      for (const uri of event.files) if (!excludedActivityPath(uri)) observeActivity({ category: 'filesystem', operation: 'workspace.file.deleted', status: 'observed', source: 'vscode-workspace', effect: 'workspace-delete', scopeRefs: [uri.fsPath] });
    }));
    if (vscode.workspace.onDidRenameFiles) subscriptions.push(vscode.workspace.onDidRenameFiles(event => {
      for (const item of event.files) if (!excludedActivityPath(item.oldUri) && !excludedActivityPath(item.newUri)) observeActivity({ category: 'filesystem', operation: 'workspace.file.renamed', status: 'observed', source: 'vscode-workspace', effect: 'workspace-write', scopeRefs: [item.oldUri.fsPath, item.newUri.fsPath] });
    }));
    const watcher = vscode.workspace.createFileSystemWatcher('**/*');
    const watcherEvent = (operation, uri) => {
      if (!settings().activity.captureFileEvents || excludedActivityPath(uri)) return; const scope = relativeScope(uri); const key = `${operation}:${scope}`;
      clearTimeout(watcherTimers.get(key)); watcherTimers.set(key, setTimeout(() => {
        watcherTimers.delete(key); observeActivity({ category: 'filesystem', operation, status: 'observed', source: 'workspace-watcher', effect: operation.endsWith('deleted') ? 'workspace-delete' : 'workspace-write', scopeRefs: [uri.fsPath], metadata: { attribution: 'unknown-external-or-editor' } }, { actor: unknownObserver('workspace-watcher'), attributeClaim: false });
      }, operation.endsWith('changed') ? 650 : 50));
    };
    subscriptions.push(watcher, watcher.onDidCreate(uri => watcherEvent('workspace.file.created', uri)), watcher.onDidChange(uri => watcherEvent('workspace.file.changed', uri)), watcher.onDidDelete(uri => watcherEvent('workspace.file.deleted', uri)));

    subscriptions.push(vscode.window.onDidOpenTerminal(terminal => {
      if (!settings().activity.captureTerminalLifecycle) return; const correlationId = `terminal-${crypto.randomUUID()}`; terminalCorrelations.set(terminal, correlationId);
      observeActivity({ category: 'terminal', operation: 'terminal.session', status: 'started', source: 'vscode-terminal', effect: 'process', correlationId, metadata: { name: terminal.name, process_id: null } });
    }), vscode.window.onDidCloseTerminal(terminal => {
      if (!settings().activity.captureTerminalLifecycle) return; const correlationId = terminalCorrelations.get(terminal) || `terminal-${crypto.randomUUID()}`;
      observeActivity({ category: 'terminal', operation: 'terminal.session', status: terminal.exitStatus?.code == null ? 'idle' : terminal.exitStatus.code === 0 ? 'succeeded' : 'failed', source: 'vscode-terminal', effect: 'process', correlationId, metadata: { name: terminal.name, exit_code: terminal.exitStatus?.code ?? null, reason: terminal.exitStatus?.reason ?? null } });
    }));
    if (typeof vscode.window.onDidStartTerminalShellExecution === 'function') subscriptions.push(vscode.window.onDidStartTerminalShellExecution(event => {
      if (!settings().activity.captureTerminalLifecycle) return; const correlationId = `shell-${crypto.randomUUID()}`; shellCorrelations.set(event.execution, correlationId);
      const command = String(event.execution.commandLine?.value || ''); const firstToken = command.trim().split(/\s+/)[0] || null;
      observeActivity({ category: 'terminal', operation: 'terminal.shell-execution', status: 'started', source: 'vscode-terminal-shell-integration', effect: 'process', correlationId, inputSha256: command ? activityHash(command) : null, metadata: { terminal_name: event.terminal.name, command_name: settings().activity.captureCommandText ? firstToken : '[disabled]', command_confidence: event.execution.commandLine?.confidence ?? null, command_trusted: event.execution.commandLine?.isTrusted ?? null } });
    }));
    if (typeof vscode.window.onDidEndTerminalShellExecution === 'function') subscriptions.push(vscode.window.onDidEndTerminalShellExecution(event => {
      if (!settings().activity.captureTerminalLifecycle) return; const correlationId = shellCorrelations.get(event.execution) || `shell-${crypto.randomUUID()}`;
      observeActivity({ category: 'terminal', operation: 'terminal.shell-execution', status: event.exitCode == null ? 'idle' : event.exitCode === 0 ? 'succeeded' : 'failed', source: 'vscode-terminal-shell-integration', effect: 'process', correlationId, metadata: { terminal_name: event.terminal.name, exit_code: event.exitCode ?? null } });
    }));

    subscriptions.push(vscode.tasks.onDidStartTask(event => {
      if (!settings().activity.captureTaskLifecycle) return; const correlationId = `taskrun-${crypto.randomUUID()}`; taskCorrelations.set(event.execution, correlationId);
      observeActivity({ category: 'task', operation: 'vscode.task', status: 'started', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, source: event.execution.task.source, scope: event.execution.task.scope?.name || null } });
    }), vscode.tasks.onDidEndTask(event => {
      if (!settings().activity.captureTaskLifecycle) return; const correlationId = taskCorrelations.get(event.execution) || `taskrun-${crypto.randomUUID()}`;
      observeActivity({ category: 'task', operation: 'vscode.task', status: 'idle', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, source: event.execution.task.source, outcome: 'process-result-separate-or-unavailable' } });
    }), vscode.tasks.onDidEndTaskProcess(event => {
      if (!settings().activity.captureTaskLifecycle) return; const correlationId = taskCorrelations.get(event.execution) || `taskrun-${crypto.randomUUID()}`;
      observeActivity({ category: 'task', operation: 'vscode.task-process', status: event.exitCode ? 'failed' : 'succeeded', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, exit_code: event.exitCode ?? null } });
    }));

    subscriptions.push(vscode.debug.onDidStartDebugSession(debugSession => {
      if (!settings().activity.captureDebugLifecycle) return; const correlationId = `debug-${crypto.randomUUID()}`; debugCorrelations.set(debugSession.id, correlationId);
      observeActivity({ category: 'debug', operation: 'debug.session', status: 'started', source: 'vscode-debug-service', effect: 'process', correlationId, metadata: { debug_type: debugSession.type, name: debugSession.name, workspace: debugSession.workspaceFolder?.name || null } });
    }), vscode.debug.onDidTerminateDebugSession(debugSession => {
      if (!settings().activity.captureDebugLifecycle) return; const correlationId = debugCorrelations.get(debugSession.id) || `debug-${crypto.randomUUID()}`; debugCorrelations.delete(debugSession.id);
      observeActivity({ category: 'debug', operation: 'debug.session', status: 'idle', source: 'vscode-debug-service', effect: 'process', correlationId, metadata: { debug_type: debugSession.type, name: debugSession.name, outcome: 'not-reported-by-debug-api' } });
    }));

    if (typeof vscode.tests?.onDidChangeTestResults === 'function') subscriptions.push(vscode.tests.onDidChangeTestResults(() => {
      if (!settings().activity.captureTestLifecycle) return; const result = vscode.tests.testResults?.[0]; if (!result) return;
      observeActivity({ category: 'test', operation: 'test.result', status: 'observed', source: 'vscode-test-service', effect: 'observe', correlationId: `test-${result.completedAt || crypto.randomUUID()}`, metadata: { completed_at: result.completedAt || null, result_count: Array.isArray(result.results) ? result.results.length : null } });
    }));

    const attachedRepositories = new WeakSet();
    const attachRepository = repository => {
      if (!repository || attachedRepositories.has(repository)) return; attachedRepositories.add(repository);
      subscriptions.push(repository.state.onDidChange(() => {
        const rootUri = repository.rootUri; const key = `scm:${rootUri.toString()}`; clearTimeout(watcherTimers.get(key)); watcherTimers.set(key, setTimeout(() => {
          watcherTimers.delete(key); const state = repository.state;
          observeActivity({ category: 'scm', operation: 'scm.repository.changed', status: 'observed', source: 'vscode-git', effect: 'workspace-read', scopeRefs: [rootUri.fsPath], metadata: { branch: state.HEAD?.name || null, commit: state.HEAD?.commit || null, working_tree_changes: state.workingTreeChanges?.length || 0, index_changes: state.indexChanges?.length || 0, merge_changes: state.mergeChanges?.length || 0, attribution: 'unknown' } }, { actor: unknownObserver('vscode-git'), attributeClaim: false });
        }, 450));
      }));
    };
    try {
      const gitExtension = vscode.extensions.getExtension('vscode.git');
      if (gitExtension?.isActive && gitExtension.exports?.getAPI) {
        const git = gitExtension.exports.getAPI(1); for (const repository of git.repositories || []) attachRepository(repository);
        if (git.onDidOpenRepository) subscriptions.push(git.onDidOpenRepository(attachRepository));
      }
    } catch (error) { codexOutput.appendLine(`SCM activity listener unavailable: ${error.message}`); }
    context.subscriptions.push(...subscriptions);
  }

  async function openDashboard() {
    if (!panel) {
      panel = vscode.window.createWebviewPanel('pacifyX.dashboard', 'PX · Control Plane', vscode.ViewColumn.One, {
        enableScripts: true, retainContextWhenHidden: false, localResourceRoots: [vscode.Uri.file(path.join(context.extensionPath, 'media'))]
      });
      panel.iconPath = vscode.Uri.file(path.join(context.extensionPath, 'media', 'px-shield-32.png'));
      panel.webview.html = getHtml(panel.webview, context.extensionPath);
      panel.webview.onDidReceiveMessage(async message => {
        try {
          switch (message?.type) {
            case 'ready':
            case 'refresh': await publishSnapshot(true); break;
            case 'catalogQuery': await panel.webview.postMessage({ type: 'catalogResult', requestId: message.requestId, result: await bridge().catalog(message) }); break;
            case 'graphQuery': await panel.webview.postMessage({ type: 'graphResult', requestId: message.requestId, result: await bridge().graph(message) }); break;
            case 'coordinationRefresh': await publishCoordination(); break;
            case 'activityQuery': {
              const root = workspaceRoot(); if (!root) throw new Error('Open a workspace before reading the activity ledger.');
              const activity = readActivity(root, { query: message.query, category: message.category, status: message.status, limit: message.limit || 120, policy: settings().activity });
              await panel.webview.postMessage({ type: 'activityResult', requestId: message.requestId, result: activity }); break;
            }
            case 'setActivityPaused': {
              await vscode.workspace.getConfiguration('pacifyX').update('activity.paused', Boolean(message.paused), vscode.ConfigurationTarget.Workspace);
              observeActivity({ category: 'policy', operation: 'observability.policy-changed', status: 'observed', source: 'dashboard', effect: 'workspace-write', metadata: { paused: Boolean(message.paused), content_policy: 'hash-or-redacted-reference-only' } });
              break;
            }
            case 'memoryQuery': {
              const root = workspaceRoot();
              if (!root) throw new Error('Open a workspace before reading project coordination memory.');
              const result = readMemoryTelemetry(root, { query: message.query, limit: message.limit, includeContent: true });
              await panel.webview.postMessage({ type: 'memoryResult', requestId: message.requestId, result }); break;
            }
            case 'createParallelPlan':
            case 'claimCoordinationTask':
            case 'renewCoordinationClaim':
            case 'recordTaskProgress':
            case 'reconcileCoordinationTask':
            case 'releaseCoordinationTask':
            case 'captureCoordinationMemory': await coordinationAction(message); break;
            case 'copyTaskHandoff': {
              const handoff = taskHandoff(workspaceRoot(), message.taskId); await vscode.env.clipboard.writeText(JSON.stringify(handoff, null, 2));
              await vscode.window.showInformationMessage('Pacify-X copied the task handoff package.'); break;
            }
            case 'openCoordinationHandoff': {
              const data = coordination(); if (!data?.paths?.handoff_markdown) break;
              const document = await vscode.workspace.openTextDocument(vscode.Uri.file(data.paths.handoff_markdown)); await vscode.window.showTextDocument(document, { preview: true }); break;
            }
            case 'openSettings': await vscode.commands.executeCommand('workbench.action.openSettings', '@ext:mountain-nomad-bc.pacify-x-vscode'); break;
            case 'validate': await validateControlPlane(); break;
            case 'createContextSnapshot': await openContextSnapshot(); break;
            case 'copyText': { const text = String(message.text || '').slice(0, 65536); if (text) { await vscode.env.clipboard.writeText(text); await vscode.window.showInformationMessage('Pacify-X copied the inspected control data.'); } break; }
            case 'exportSnapshot': { if (!currentSnapshot) await publishSnapshot(); const document = await vscode.workspace.openTextDocument({ content: `${JSON.stringify(currentSnapshot, null, 2)}\n`, language: 'json' }); await vscode.window.showTextDocument(document, { preview: true }); break; }
            case 'exportRecordJson': {
              const serialized = `${JSON.stringify(message.record ?? null, null, 2)}\n`;
              if (Buffer.byteLength(serialized, 'utf8') > 4 * 1024 * 1024) throw new Error('Record export exceeds the 4 MiB safety limit.');
              const safeName = String(message.fileName || message.title || 'pacify-x-record').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 120) || 'pacify-x-record';
              const target = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(workspaceRoot() || engineRoot() || context.globalStorageUri.fsPath, `${safeName}.json`)), filters: { JSON: ['json'] }, saveLabel: 'Export Pacify-X JSON' });
              if (target) { await vscode.workspace.fs.writeFile(target, Buffer.from(serialized, 'utf8')); await vscode.window.showInformationMessage(`Pacify-X exported ${path.basename(target.fsPath)}.`); }
              break;
            }
            case 'openExtensionsView': await vscode.commands.executeCommand('workbench.view.extensions'); break;
            case 'scanCleanup': await publishCleanupCandidates(); break;
            case 'executeCleanup': await performCleanup(message); break;
            case 'teamPackPreview': await previewTeamPack(); break;
            case 'enterprisePackToggle':
            case 'enterpriseTargetConfigure':
            case 'enterpriseDoctor':
            case 'toggleBillablePolicy': await enterpriseAction(message); break;
            case 'refreshEnvironment': await refreshEnvironment('manual-refresh', true); break;
            case 'environmentQuery': await panel.webview.postMessage({ type: 'environmentResult', subject: message.subject, result: readEnvironmentSubject(workspaceRoot(), message.subject, { query: message.query, offset: message.offset, limit: message.limit }) }); break;
            case 'environmentExtensionDetail': await panel.webview.postMessage({ type: 'environmentExtensionDetail', result: readEnvironmentExtension(workspaceRoot(), String(message.extensionId || '')) }); break;
            case 'continueCodex': await continueWithCodex(); break;
            case 'cancelCodex': if (!codexRuns.cancel()) await vscode.window.showInformationMessage('No Pacify-X bridge-owned Codex run is active.'); break;
            case 'openFile': {
              const roots = [engineRoot(), workspaceRoot()]; let admitted = false;
              try { admitted = Boolean(message.path && isPathWithin(message.path, roots) && fs.statSync(message.path).isFile()); } catch { admitted = false; }
              if (!admitted) { await vscode.window.showWarningMessage('Pacify-X refused to open a path outside admitted roots.'); break; }
              const document = await vscode.workspace.openTextDocument(vscode.Uri.file(message.path)); await vscode.window.showTextDocument(document, { preview: true }); break;
            }
            case 'previewGovernedAction': await vscode.window.showInformationMessage(`Pacify-X preview: ${String(message.action || 'advanced action')} requires its owning Pacify-X controller and admission receipt.`); break;
            default: break;
          }
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          await panel?.webview.postMessage({ type: 'operationError', operation: message?.type || 'unknown', error: detail });
          await vscode.window.showErrorMessage(`Pacify-X ${message?.type || 'operation'} failed closed: ${detail}`);
        }
      }, undefined, context.subscriptions);
      panel.onDidDispose(() => { panel = undefined; clearInterval(refreshTimer); refreshTimer = undefined; }, undefined, context.subscriptions);
    } else panel.reveal(vscode.ViewColumn.One);
    await publishSnapshot(true);
    clearInterval(refreshTimer);
    refreshTimer = setInterval(() => { if (panel?.visible) void publishSnapshot(); }, Math.max(5, settings().refreshIntervalSeconds) * 1000);
  }

  registerActivityHooks();
  context.subscriptions.push(
    vscode.commands.registerCommand('pacifyX.openDashboard', openDashboard),
    vscode.commands.registerCommand('pacifyX.refreshDashboard', () => publishSnapshot(true)),
    vscode.commands.registerCommand('pacifyX.validateControlPlane', validateControlPlane),
    vscode.commands.registerCommand('pacifyX.createContextSnapshot', openContextSnapshot),
    vscode.commands.registerCommand('pacifyX.openCleanupManager', async () => { await openDashboard(); await publishCleanupCandidates(); }),
    vscode.commands.registerCommand('pacifyX.continueWithCodex', continueWithCodex),
    vscode.commands.registerCommand('pacifyX.cancelCodex', () => codexRuns.cancel()),
    vscode.commands.registerCommand('pacifyX.refreshProviderStatus', () => publishSnapshot(true)),
    vscode.commands.registerCommand('pacifyX.refreshEnvironment', () => refreshEnvironment('command-refresh', true)),
    vscode.commands.registerCommand('pacifyX.openSettings', () => vscode.commands.executeCommand('workbench.action.openSettings', '@ext:mountain-nomad-bc.pacify-x-vscode')),
    vscode.workspace.onDidChangeConfiguration(event => {
      if (!event.affectsConfiguration('pacifyX')) return;
      activeRuntime.bridge?.update({ pythonPath: settings().pythonPath, engineRoot: engineRoot(), workspaceRoot: settings().workspaceRoot || undefined });
      clearInterval(refreshTimer);
      if (panel) refreshTimer = setInterval(() => { if (panel?.visible) void publishSnapshot(); }, Math.max(5, settings().refreshIntervalSeconds) * 1000);
      if (event.affectsConfiguration('pacifyX.billable') || event.affectsConfiguration('pacifyX.guardrails')) {
        try { if (workspaceRoot() && currentSnapshot?.enterprise?.catalog_id) setExecutionPolicy(workspaceRoot(), currentSnapshot.enterprise, settings().executionPolicy); }
        catch (error) { void vscode.window.showErrorMessage(`Pacify-X guardrail update failed closed: ${error.message}`); }
      }
      if (event.affectsConfiguration('pacifyX.activity')) observeActivity({ category: 'policy', operation: 'observability.configuration-changed', status: 'observed', source: 'vscode-configuration', effect: 'workspace-write', metadata: { policy: settings().activity } });
      void panel?.webview.postMessage({ type: 'settings', settings: settings() }); void publishSnapshot(true);
    })
  );
  if (vscode.extensions.onDidChange) context.subscriptions.push(vscode.extensions.onDidChange(() => {
    observeActivity({ category: 'environment', operation: 'vscode.extensions.changed', status: 'observed', source: 'vscode-extension-service', effect: 'workspace-read' });
    void refreshEnvironment('vscode-extension-change', false);
  }));

  if (vscode.lm?.registerMcpServerDefinitionProvider && vscode.McpStdioServerDefinition) {
    context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider('pacify-x.mcp', {
      provideMcpServerDefinitions() {
        const definition = new vscode.McpStdioServerDefinition('Pacify-X Governed Context', process.execPath, [path.join(context.extensionPath, 'server', 'index.js')], {
          ELECTRON_RUN_AS_NODE: '1', PX_CONTEXT_PATH: contextPath, PX_ENGINE_ROOT: engineRoot() || '',
          PX_WORKSPACE_ROOT: workspaceRoot() || '', PX_COORDINATION_ROOT: workspaceRoot() || '',
          PX_PYTHON_PATH: settings().pythonPath,
          PX_ENVIRONMENT_PATH: environmentPathsFor(workspaceRoot()).current,
          PX_ACTIVITY_POLICY: JSON.stringify(settings().activity)
        }, context.extension.packageJSON?.version || '0.5.0');
        definition.cwd = vscode.Uri.file(context.extensionPath); return [definition];
      }
    }));
  }

  if (vscode.lm?.registerLanguageModelChatProvider) {
    const ollama = new OllamaChatProvider(vscode, () => settings().ollamaEnabled ? settings().ollamaBaseUrl : '');
    context.subscriptions.push(ollama, vscode.lm.registerLanguageModelChatProvider('pacify-local', ollama));
    context.subscriptions.push(vscode.commands.registerCommand('pacifyX.refreshOllama', () => ollama.refresh()));
  } else context.subscriptions.push(vscode.commands.registerCommand('pacifyX.refreshOllama', () => vscode.window.showInformationMessage('Pacify-X local model provider is unavailable in this host.')));

  void publishSnapshot(true).then(() => refreshEnvironment('startup', false)).catch(error => codexOutput.appendLine(`Environment discovery failed closed: ${error.message}`));
}

function deactivate() { clearInterval(refreshTimer); activeRuntime = undefined; currentEnvironment = undefined; }

module.exports = { activate, deactivate, portableContextSnapshot, liveContextEnvelope, getHtml, actorIdentity };
