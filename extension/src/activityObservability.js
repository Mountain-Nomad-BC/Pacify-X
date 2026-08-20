'use strict';

const crypto = require('crypto');
const { SDK_VERSION, buildOperationEvent } = require('./instrumentationSdk');

const LISTENER_IDS = Object.freeze([
  'editor', 'filesystem', 'filesystem-watcher', 'terminal', 'terminal-shell',
  'task', 'debug', 'test', 'scm', 'configuration', 'extensions'
]);
const MAX_PENDING_WATCHER_PATHS = 256;
const MAX_WATCHER_SCOPE_REFS = 64;

function sha(value) { return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
function clean(value, fallback = null) {
  const normalized = String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 180);
  return normalized || fallback;
}
function effect(value) {
  const source = String(value || 'read');
  if (source === 'process') return 'process';
  if (/delete|destructive/.test(source)) return 'destructive';
  if (/write/.test(source)) return 'write';
  if (source === 'ui') return 'ui';
  return 'read';
}
function lifecycle(status) {
  return ({ started: ['started', 'pending'], running: ['progress', 'pending'], succeeded: ['completed', 'success'], failed: ['failed', 'failure'], cancelled: ['cancelled', 'cancelled'], blocked: ['denied', 'denied'], idle: ['completed', 'unknown'], observed: ['progress', 'unknown'] })[status] || ['unknown', 'unknown'];
}

function buildActivityAttestation(input, actor, context = {}) {
  const [operationLifecycle, result] = lifecycle(input.status);
  const isListener = LISTENER_IDS.includes(input.listenerId);
  const event = buildOperationEvent({
    sdk_version: SDK_VERSION,
    event_id: `extension-${context.uuid?.() || crypto.randomUUID()}`,
    correlation_id: clean(input.correlationId || input.correlation_id, `extension-${context.uuid?.() || crypto.randomUUID()}`),
    parent_correlation_id: null,
    actor: {
      actor_id: clean(actor.actorId || actor.actor_id, 'unknown-actor'),
      actor_kind: isListener ? 'extension' : 'agent',
      session_id: clean(actor.sessionId || actor.session_id, 'unknown-session'),
      harness: String(actor.harness || 'VS Code').slice(0, 120),
      accountable_owner: String(actor.accountableOwner || actor.accountable_owner || 'unknown').slice(0, 160)
    },
    work: {
      project_id: clean(context.projectId, 'unresolved-project'),
      task_id: clean(input.taskId || input.task_id),
      claim_id: clean(input.claimId || input.claim_id),
      orchestration_id: clean(input.orchestrationId || input.orchestration_id)
    },
    source: {
      route_id: isListener ? 'extension.vscode-listener' : 'extension.command',
      component: isListener ? 'src/activityObservability.js' : 'src/extension.js',
      host_id: clean(context.hostId),
      coverage_tier: isListener ? 'B' : 'C'
    },
    operation: { name: String(input.operation || 'activity.unknown').slice(0, 200), lifecycle: operationLifecycle, result },
    effects: {
      declared: [effect(input.effect)], observed: [effect(input.effect)],
      scope_refs: [`project:${clean(context.projectId, 'unresolved-project')}`, `scope-count:${(input.scopeRefs || input.scope_refs || []).length}`]
    },
    provider: null,
    time: { observed_at: context.now?.() || new Date().toISOString(), started_at: operationLifecycle === 'started' ? (context.now?.() || new Date().toISOString()) : null, duration_ms: input.durationMs ?? input.duration_ms ?? null, freshness: 'live' },
    integrity: { input_sha256: null, output_sha256: null, previous_event_sha256: null },
    capture: { classification: 'metadata_only', payload_included: false }
  });
  const attestation = { schema_version: event.schema_version, sdk_version: SDK_VERSION, event_sha256: sha(event), route_id: event.source.route_id, coverage_tier: event.source.coverage_tier, payload_retained: false };
  Object.defineProperty(attestation, 'canonicalEvent', { value: event, enumerable: false });
  return attestation;
}

class ListenerHealth {
  constructor(inventory = {}) {
    this.bus = { connected: false, status: 'unconfigured', published_events: 0, dropped_events: 0, last_error_code: null };
    this.rows = Object.fromEntries(LISTENER_IDS.map(id => [id, {
      listener_id: id, api_available: Boolean(inventory[id]?.available), enabled: inventory[id]?.enabled !== false,
      required: inventory[id]?.required !== false,
      health: !inventory[id]?.available ? 'unsupported' : inventory[id]?.enabled === false ? 'disabled' : 'unexercised',
      registered: false, events_recorded: 0, dropped_events: 0, last_drop_reason: null, limitation: inventory[id]?.limitation || null
    }]));
  }
  recordBus(result = {}) {
    if (result.connected) {
      this.bus.connected = true; this.bus.status = 'healthy'; this.bus.published_events += Number(result.published || 0); this.bus.last_error_code = null;
    } else {
      this.bus.connected = false; this.bus.status = result.status || 'degraded'; this.bus.dropped_events += Number(result.dropped || 0); this.bus.last_error_code = result.error_code || null;
    }
  }
  record(id, result) {
    const row = this.rows[id]; if (!row) return;
    if (result?.recorded) { row.registered = true; row.events_recorded += 1; if (row.api_available && row.enabled && row.dropped_events === 0) row.health = 'healthy'; }
    else { row.dropped_events += 1; row.health = 'degraded'; row.last_drop_reason = String(result?.reason || 'unknown').slice(0, 120); }
  }
  markRegistered(inventory = {}) {
    for (const id of LISTENER_IDS) {
      const row = this.rows[id];
      if (inventory[id]?.available && inventory[id]?.enabled !== false) {
        row.registered = true;
        if (row.dropped_events === 0) row.health = 'healthy';
      }
    }
    return this.snapshot();
  }
  reconcile(inventory = {}) {
    for (const id of LISTENER_IDS) {
      const row = this.rows[id];
      row.api_available = Boolean(inventory[id]?.available);
      row.enabled = inventory[id]?.enabled !== false;
      row.required = inventory[id]?.required !== false;
      row.limitation = inventory[id]?.limitation || null;
      row.health = row.dropped_events > 0 ? 'degraded' : !row.api_available ? 'unsupported' : !row.enabled ? 'disabled' : row.registered ? 'healthy' : 'unexercised';
    }
    return this.snapshot();
  }
  snapshot() {
    const listeners = LISTENER_IDS.map(id => ({ ...this.rows[id] }));
    const incomplete = listeners.filter(row => row.required && row.api_available && row.enabled && row.health !== 'healthy');
    const unsupported = listeners.filter(row => row.required && !row.api_available);
    const degraded = listeners.some(row => row.health === 'degraded') || this.bus.status === 'degraded';
    return {
      schema_version: 'px.vscode-listener-health/1.1', listeners,
      available: listeners.filter(row => row.api_available).length,
      unavailable: listeners.filter(row => !row.api_available).length,
      dropped_events: listeners.reduce((sum, row) => sum + row.dropped_events, 0),
      status: degraded ? 'degraded' : incomplete.length || !this.bus.connected ? 'partial' : 'healthy',
      coverage_complete: incomplete.length === 0 && this.bus.connected,
      incomplete_listener_ids: incomplete.map(row => row.listener_id),
      canonical_bus_connected: this.bus.connected,
      canonical_bus: { ...this.bus },
      coverage_tier: 'B',
      limitations: [
        ...(this.bus.connected ? [] : ['Canonical-bus publication is unavailable or unhealthy; project activity attestations remain available.']),
        ...unsupported.map(row => `${row.listener_id}:unsupported${row.limitation ? `:${row.limitation}` : ''}`),
        ...incomplete.map(row => `${row.listener_id}:${row.health}${row.limitation ? `:${row.limitation}` : ''}`)
      ]
    };
  }
}

class ListenerRegistrationGate {
  constructor() { this.registration = null; this.disposed = false; }
  start(factory) {
    if (this.disposed) throw new Error('listener-registration-gate-disposed');
    if (!this.registration) this.registration = factory();
    return this.registration;
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true; this.registration?.dispose?.(); this.registration = null;
  }
}

function listenerApiInventory(vscode, settings) {
  const callable = value => typeof value === 'function';
  const safeApi = (object, key) => { try { return object?.[key]; } catch { return undefined; } };
  const enabled = settings?.activity || {};
  const gitExtension = vscode.extensions?.getExtension?.('vscode.git');
  return {
    editor: { available: callable(vscode.workspace?.onDidChangeTextDocument), enabled: enabled.captureFileEvents !== false },
    filesystem: { available: callable(vscode.workspace?.onDidCreateFiles) && callable(vscode.workspace?.onDidDeleteFiles) && callable(vscode.workspace?.onDidRenameFiles), enabled: enabled.captureFileEvents !== false },
    'filesystem-watcher': { available: callable(vscode.workspace?.createFileSystemWatcher), enabled: enabled.captureFileEvents !== false },
    terminal: { available: callable(vscode.window?.onDidOpenTerminal) && callable(vscode.window?.onDidCloseTerminal), enabled: enabled.captureTerminalLifecycle !== false },
    'terminal-shell': { available: callable(vscode.window?.onDidStartTerminalShellExecution) && callable(vscode.window?.onDidEndTerminalShellExecution), enabled: enabled.captureTerminalLifecycle !== false, limitation: 'Requires VS Code terminal shell-integration API.' },
    task: { available: callable(vscode.tasks?.onDidStartTask) && callable(vscode.tasks?.onDidEndTask), enabled: enabled.captureTaskLifecycle !== false },
    debug: { available: callable(vscode.debug?.onDidStartDebugSession) && callable(vscode.debug?.onDidTerminateDebugSession), enabled: enabled.captureDebugLifecycle !== false },
    test: { available: callable(safeApi(vscode.tests, 'onDidChangeTestResults')), enabled: enabled.captureTestLifecycle !== false, limitation: 'The test-result event is proposed/host-gated in some VS Code builds; unavailable getters are reported instead of breaking activation.' },
    scm: { available: Boolean(gitExtension?.isActive && callable(gitExtension.exports?.getAPI)), enabled: true, limitation: 'Git extension activation and API v1 are required.' },
    configuration: { available: callable(vscode.workspace?.onDidChangeConfiguration), enabled: true },
    extensions: { available: callable(vscode.extensions?.onDidChange), enabled: true }
  };
}

function registerActivityListeners(options) {
  const {
    vscode, context, settings, workspaceRoot, observeActivity, unknownObserver,
    excludedActivityPath, relativeScope, output, onConfigurationChanged, onExtensionsChanged,
    bindConfigurationAndExtensions = true, schedule = setTimeout, cancelSchedule = clearTimeout,
    faultInjector,
    delays = { editor: 900, watcherChange: 650, watcherOther: 50, scm: 450 }
  } = options;
  const subscriptions = [];
  const editAggregates = new Map();
  const delayedEvents = new Map();
  const watcherEvents = new Map();
  let watcherTimer = null;
  let watcherOverflow = 0;
  const terminalCorrelations = new WeakMap();
  const shellCorrelations = new WeakMap();
  const taskCorrelations = new WeakMap();
  const debugCorrelations = new Map();
  const callable = value => typeof value === 'function';
  const safeApi = (object, key) => { try { return object?.[key]; } catch { return undefined; } };
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    for (const aggregate of editAggregates.values()) cancelSchedule(aggregate.timer);
    for (const timer of delayedEvents.values()) cancelSchedule(timer);
    cancelSchedule(watcherTimer); watcherTimer = null;
    editAggregates.clear(); delayedEvents.clear(); watcherEvents.clear(); watcherOverflow = 0;
    for (const subscription of [...subscriptions].reverse()) {
      try { subscription?.dispose?.(); } catch (error) { output?.appendLine?.(`Activity listener disposal failed closed: ${error.message}`); }
    }
    subscriptions.length = 0;
  };
  const own = (subscription, label) => {
    if (!subscription || typeof subscription.dispose !== 'function') throw new Error(`invalid-listener-disposable:${label}`);
    subscriptions.push(subscription);
    faultInjector?.({ label, registered: subscriptions.length });
    return subscription;
  };
  const observeListener = (listenerId, input, listenerOptions = {}) => observeActivity(
    { ...input, listenerId }, { ...listenerOptions, listenerId }
  );
  const listen = (source, callback, label = 'listener') => {
    if (!callable(source)) return false;
    own(source(callback), label);
    return true;
  };
  const observeDocument = (operation, document, status = 'observed', metadata = {}) => {
    if (!settings().activity.captureFileEvents || document?.uri?.scheme !== 'file' || excludedActivityPath(document.uri)) return;
    observeListener('editor', {
      category: 'editor', operation, status, source: 'vscode-editor', effect: 'workspace-read',
      scopeRefs: [document.uri.fsPath], metadata: { language_id: document.languageId, version: document.version, ...metadata }
    });
  };
  const flushEdit = key => {
    const aggregate = editAggregates.get(key);
    if (!aggregate) return;
    editAggregates.delete(key);
    cancelSchedule(aggregate.timer);
    observeDocument('editor.document.changed', aggregate.document, 'observed', {
      change_batches: aggregate.batches, changed_regions: aggregate.regions,
      inserted_bytes: aggregate.insertedBytes, deleted_units: aggregate.deletedUnits,
      first_change_utc: aggregate.firstChangeUtc
    });
  };

  try {
  listen(vscode.workspace?.onDidChangeTextDocument, event => {
    if (!settings().activity.captureFileEvents || event.document.uri.scheme !== 'file' || excludedActivityPath(event.document.uri) || !event.contentChanges.length) return;
    const key = event.document.uri.toString();
    const existing = editAggregates.get(key) || {
      document: event.document, batches: 0, regions: 0, insertedBytes: 0,
      deletedUnits: 0, firstChangeUtc: new Date().toISOString(), timer: null
    };
    existing.document = event.document;
    existing.batches += 1;
    existing.regions += event.contentChanges.length;
    for (const change of event.contentChanges) {
      existing.insertedBytes += Buffer.byteLength(change.text || '', 'utf8');
      existing.deletedUnits += Number(change.rangeLength || 0);
    }
    cancelSchedule(existing.timer);
    existing.timer = schedule(() => flushEdit(key), delays.editor);
    editAggregates.set(key, existing);
  });
  listen(vscode.workspace?.onDidSaveTextDocument, document => {
    flushEdit(document.uri.toString());
    if (!settings().activity.captureFileEvents || document.uri.scheme !== 'file' || excludedActivityPath(document.uri)) return;
    observeDocument('editor.document.saved', document, 'succeeded', {
      bytes: Buffer.byteLength(document.getText(), 'utf8'), content_fingerprint_omitted: true
    });
  });
  listen(vscode.workspace?.onDidOpenTextDocument, document => observeDocument('editor.document.opened', document));
  listen(vscode.workspace?.onDidCloseTextDocument, document => {
    flushEdit(document.uri.toString());
    observeDocument('editor.document.closed', document, 'idle');
  });
  listen(vscode.workspace?.onDidCreateFiles, event => {
    for (const uri of event.files) if (!excludedActivityPath(uri)) observeListener('filesystem', {
      category: 'filesystem', operation: 'workspace.file.created', status: 'observed', source: 'vscode-workspace', effect: 'observe', scopeRefs: [uri.fsPath], metadata: { observed_effect: 'workspace-write', attribution: 'unknown' }
    });
  });
  listen(vscode.workspace?.onDidDeleteFiles, event => {
    for (const uri of event.files) if (!excludedActivityPath(uri)) observeListener('filesystem', {
      category: 'filesystem', operation: 'workspace.file.deleted', status: 'observed', source: 'vscode-workspace', effect: 'observe', scopeRefs: [uri.fsPath], metadata: { observed_effect: 'workspace-delete', attribution: 'unknown' }
    });
  });
  listen(vscode.workspace?.onDidRenameFiles, event => {
    for (const item of event.files) if (!excludedActivityPath(item.oldUri) && !excludedActivityPath(item.newUri)) observeListener('filesystem', {
      category: 'filesystem', operation: 'workspace.file.renamed', status: 'observed', source: 'vscode-workspace', effect: 'observe', scopeRefs: [item.oldUri.fsPath, item.newUri.fsPath], metadata: { observed_effect: 'workspace-write', attribution: 'unknown' }
    });
  });

  if (callable(vscode.workspace?.createFileSystemWatcher)) {
    const root = workspaceRoot();
    const admittedPattern = '**/{src,runtime,tests,extension,registry,contracts,docs}/**';
    const watcherPattern = root && vscode.RelativePattern ? new vscode.RelativePattern(root, admittedPattern) : admittedPattern;
    const watcher = own(vscode.workspace.createFileSystemWatcher(watcherPattern), 'filesystem-watcher');
    const flushWatcherEvents = () => {
      cancelSchedule(watcherTimer); watcherTimer = null;
      if (!watcherEvents.size && !watcherOverflow) return;
      const grouped = new Map();
      for (const item of watcherEvents.values()) {
        const group = grouped.get(item.operation) || { count: 0, scopes: [], sampleUri: item.uri };
        group.count += 1;
        if (group.scopes.length < MAX_WATCHER_SCOPE_REFS) group.scopes.push(item.uri.fsPath);
        grouped.set(item.operation, group);
      }
      watcherEvents.clear();
      const overflow = watcherOverflow; watcherOverflow = 0;
      for (const [operation, group] of grouped) observeListener('filesystem-watcher', {
        category: 'filesystem', operation, status: 'observed', source: 'workspace-watcher',
        effect: 'observe', scopeRefs: group.scopes,
        metadata: {
          attribution: 'unknown-external-or-editor', coalesced: true, event_count: group.count,
          scope_refs_capped: group.count > group.scopes.length, overflow_events: overflow,
          observed_effect: operation.endsWith('deleted') ? 'workspace-delete' : 'workspace-write'
        }
      }, { actor: unknownObserver('workspace-watcher'), attributeClaim: false });
    };
    const watcherEvent = (operation, uri) => {
      if (!settings().activity.captureFileEvents || excludedActivityPath(uri)) return;
      const scope = relativeScope(uri);
      const key = `${operation}:${scope}`;
      if (watcherEvents.has(key)) watcherEvents.set(key, { operation, uri });
      else if (watcherEvents.size < MAX_PENDING_WATCHER_PATHS) watcherEvents.set(key, { operation, uri });
      else watcherOverflow += 1;
      // One leading-edge timer prevents an uninterrupted build from continually
      // postponing delivery or allocating a timer for every changed path.
      if (!watcherTimer) watcherTimer = schedule(flushWatcherEvents, operation.endsWith('changed') ? delays.watcherChange : delays.watcherOther);
    };
    listen(watcher.onDidCreate, uri => watcherEvent('workspace.file.created', uri));
    listen(watcher.onDidChange, uri => watcherEvent('workspace.file.changed', uri));
    listen(watcher.onDidDelete, uri => watcherEvent('workspace.file.deleted', uri));
  }

  listen(vscode.window?.onDidOpenTerminal, terminal => {
    if (!settings().activity.captureTerminalLifecycle) return;
    const correlationId = `terminal-${crypto.randomUUID()}`;
    terminalCorrelations.set(terminal, correlationId);
    observeListener('terminal', { category: 'terminal', operation: 'terminal.session', status: 'observed', source: 'vscode-terminal', effect: 'read', correlationId, metadata: { lifecycle: 'opened', name: terminal.name, process_id: null } });
  });
  listen(vscode.window?.onDidCloseTerminal, terminal => {
    if (!settings().activity.captureTerminalLifecycle) return;
    const correlationId = terminalCorrelations.get(terminal) || `terminal-${crypto.randomUUID()}`;
    observeListener('terminal', {
      category: 'terminal', operation: 'terminal.session', status: 'observed',
      source: 'vscode-terminal', effect: 'read', correlationId,
      metadata: { lifecycle: 'closed', name: terminal.name, exit_code: terminal.exitStatus?.code ?? null, reason: terminal.exitStatus?.reason ?? null }
    });
  });
  listen(vscode.window?.onDidStartTerminalShellExecution, event => {
    if (!settings().activity.captureTerminalLifecycle) return;
    const correlationId = `shell-${crypto.randomUUID()}`;
    shellCorrelations.set(event.execution, correlationId);
    const command = String(event.execution.commandLine?.value || '');
    const firstToken = command.trim().split(/\s+/)[0] || null;
    observeListener('terminal-shell', {
      category: 'terminal', operation: 'terminal.shell-execution', status: 'started', source: 'vscode-terminal-shell-integration', effect: 'process', correlationId,
      metadata: { terminal_name: event.terminal.name, command_name: settings().activity.captureCommandText ? firstToken : '[disabled]', command_fingerprint_omitted: true, command_confidence: event.execution.commandLine?.confidence ?? null, command_trusted: event.execution.commandLine?.isTrusted ?? null }
    });
  });
  listen(vscode.window?.onDidEndTerminalShellExecution, event => {
    if (!settings().activity.captureTerminalLifecycle) return;
    const correlationId = shellCorrelations.get(event.execution) || `shell-${crypto.randomUUID()}`;
    observeListener('terminal-shell', {
      category: 'terminal', operation: 'terminal.shell-execution', status: event.exitCode == null ? 'idle' : event.exitCode === 0 ? 'succeeded' : 'failed',
      source: 'vscode-terminal-shell-integration', effect: 'process', correlationId,
      metadata: { terminal_name: event.terminal.name, exit_code: event.exitCode ?? null }
    });
  });

  listen(vscode.tasks?.onDidStartTask, event => {
    if (!settings().activity.captureTaskLifecycle) return;
    const correlationId = `taskrun-${crypto.randomUUID()}`;
    taskCorrelations.set(event.execution, correlationId);
    observeListener('task', { category: 'task', operation: 'vscode.task', status: 'started', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, source: event.execution.task.source, scope: event.execution.task.scope?.name || null } });
  });
  listen(vscode.tasks?.onDidEndTask, event => {
    if (!settings().activity.captureTaskLifecycle) return;
    const correlationId = taskCorrelations.get(event.execution) || `taskrun-${crypto.randomUUID()}`;
    observeListener('task', { category: 'task', operation: 'vscode.task', status: 'idle', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, source: event.execution.task.source, outcome: 'process-result-separate-or-unavailable' } });
  });
  listen(vscode.tasks?.onDidEndTaskProcess, event => {
    if (!settings().activity.captureTaskLifecycle) return;
    const correlationId = taskCorrelations.get(event.execution) || `taskrun-${crypto.randomUUID()}`;
    observeListener('task', { category: 'task', operation: 'vscode.task-process', status: event.exitCode ? 'failed' : 'succeeded', source: 'vscode-task-service', effect: 'process', correlationId, metadata: { name: event.execution.task.name, exit_code: event.exitCode ?? null } });
  });

  listen(vscode.debug?.onDidStartDebugSession, debugSession => {
    if (!settings().activity.captureDebugLifecycle) return;
    const correlationId = `debug-${crypto.randomUUID()}`;
    debugCorrelations.set(debugSession.id, correlationId);
    observeListener('debug', { category: 'debug', operation: 'debug.session', status: 'started', source: 'vscode-debug-service', effect: 'process', correlationId, metadata: { debug_type: debugSession.type, name: debugSession.name, workspace: debugSession.workspaceFolder?.name || null } });
  });
  listen(vscode.debug?.onDidTerminateDebugSession, debugSession => {
    if (!settings().activity.captureDebugLifecycle) return;
    const correlationId = debugCorrelations.get(debugSession.id) || `debug-${crypto.randomUUID()}`;
    debugCorrelations.delete(debugSession.id);
    observeListener('debug', { category: 'debug', operation: 'debug.session', status: 'idle', source: 'vscode-debug-service', effect: 'process', correlationId, metadata: { debug_type: debugSession.type, name: debugSession.name, outcome: 'not-reported-by-debug-api' } });
  });

  listen(safeApi(vscode.tests, 'onDidChangeTestResults'), () => {
    if (!settings().activity.captureTestLifecycle) return;
    const result = safeApi(vscode.tests, 'testResults')?.[0];
    if (!result) return;
    observeListener('test', { category: 'test', operation: 'test.result', status: 'observed', source: 'vscode-test-service', effect: 'observe', correlationId: `test-${result.completedAt || crypto.randomUUID()}`, metadata: { completed_at: result.completedAt || null, result_count: Array.isArray(result.results) ? result.results.length : null } });
  });

  const attachedRepositories = new WeakSet();
  const attachRepository = repository => {
    if (!repository || attachedRepositories.has(repository)) return;
    attachedRepositories.add(repository);
    listen(repository.state?.onDidChange, () => {
      const rootUri = repository.rootUri;
      const key = `scm:${rootUri.toString()}`;
      cancelSchedule(delayedEvents.get(key));
      delayedEvents.set(key, schedule(() => {
        delayedEvents.delete(key);
        const state = repository.state;
        observeListener('scm', {
          category: 'scm', operation: 'scm.repository.changed', status: 'observed', source: 'vscode-git', effect: 'workspace-read', scopeRefs: [rootUri.fsPath],
          metadata: { branch: state.HEAD?.name || null, commit: state.HEAD?.commit || null, working_tree_changes: state.workingTreeChanges?.length || 0, index_changes: state.indexChanges?.length || 0, merge_changes: state.mergeChanges?.length || 0, attribution: 'unknown' }
        }, { actor: unknownObserver('vscode-git'), attributeClaim: false });
      }, delays.scm));
    });
  };
  try {
    const gitExtension = vscode.extensions?.getExtension?.('vscode.git');
    if (gitExtension?.isActive && callable(gitExtension.exports?.getAPI)) {
      const git = gitExtension.exports.getAPI(1);
      for (const repository of git.repositories || []) attachRepository(repository);
      listen(git.onDidOpenRepository, attachRepository);
    }
  } catch (error) {
    output?.appendLine?.(`SCM activity listener unavailable: ${error.message}`);
  }

  if (bindConfigurationAndExtensions) {
    listen(vscode.workspace?.onDidChangeConfiguration, event => {
      if (!event.affectsConfiguration('pacifyX')) return;
      if (event.affectsConfiguration('pacifyX.activity')) observeListener('configuration', {
        category: 'policy', operation: 'observability.configuration-changed', status: 'observed', source: 'vscode-configuration', effect: 'observe', metadata: { observed_effect: 'configuration-change', policy: settings().activity }
      });
      onConfigurationChanged?.(event);
    });
    listen(vscode.extensions?.onDidChange, () => {
      observeListener('extensions', { category: 'environment', operation: 'vscode.extensions.changed', status: 'observed', source: 'vscode-extension-service', effect: 'workspace-read' });
      onExtensionsChanged?.();
    });
  }

  return { subscriptions, dispose, flushPendingEdits: () => [...editAggregates.keys()].forEach(flushEdit) };
  } catch (error) {
    dispose();
    throw error;
  }
}

module.exports = {
  LISTENER_IDS, MAX_PENDING_WATCHER_PATHS, MAX_WATCHER_SCOPE_REFS,
  ListenerHealth, ListenerRegistrationGate, buildActivityAttestation, listenerApiInventory, registerActivityListeners
};
