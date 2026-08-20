'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  LISTENER_IDS, MAX_PENDING_WATCHER_PATHS, MAX_WATCHER_SCOPE_REFS,
  ListenerHealth, ListenerRegistrationGate, buildActivityAttestation, listenerApiInventory, registerActivityListeners
} = require('../src/activityObservability');

function emitter() {
  const listeners = new Set();
  const event = callback => { listeners.add(callback); return { dispose: () => listeners.delete(callback) }; };
  event.fire = value => { for (const callback of [...listeners]) callback(value); };
  event.count = () => listeners.size;
  return event;
}

test('listener inventory exposes every required API and explicit unsupported state', () => {
  const fn = () => {};
  const vscode = {
    workspace: { onDidChangeTextDocument: fn, onDidCreateFiles: fn, onDidDeleteFiles: fn, onDidRenameFiles: fn, createFileSystemWatcher: fn, onDidChangeConfiguration: fn },
    window: { onDidOpenTerminal: fn, onDidCloseTerminal: fn }, tasks: { onDidStartTask: fn, onDidEndTask: fn },
    debug: { onDidStartDebugSession: fn, onDidTerminateDebugSession: fn }, tests: {},
    extensions: { getExtension: () => null, onDidChange: fn }
  };
  const inventory = listenerApiInventory(vscode, { activity: {} });
  assert.deepEqual(Object.keys(inventory).sort(), [...LISTENER_IDS].sort());
  assert.equal(inventory.editor.available, true);
  assert.equal(inventory['terminal-shell'].available, false);
  assert.match(inventory['terminal-shell'].limitation, /shell-integration/);
  assert.equal(inventory.scm.available, false);
});

test('listener health counts drops without fabricating coverage', () => {
  const health = new ListenerHealth(Object.fromEntries(LISTENER_IDS.map(id => [id, { available: id !== 'test', enabled: true }])));
  health.record('editor', { recorded: true });
  health.record('editor', { recorded: false, reason: 'ledger-degraded' });
  const report = health.snapshot();
  const editor = report.listeners.find(row => row.listener_id === 'editor');
  const tests = report.listeners.find(row => row.listener_id === 'test');
  assert.equal(editor.events_recorded, 1);
  assert.equal(editor.dropped_events, 1);
  assert.equal(report.status, 'degraded');
  assert.equal(tests.health, 'unsupported');
  assert.equal(report.canonical_bus_connected, false);
  health.recordBus({ connected: true, published: 3 });
  assert.equal(health.snapshot().canonical_bus_connected, true);
  assert.equal(health.snapshot().canonical_bus.published_events, 3);
  health.reconcile(Object.fromEntries(LISTENER_IDS.map(id => [id, { available: true, enabled: id !== 'task' }])));
  assert.equal(health.snapshot().listeners.find(row => row.listener_id === 'test').health, 'unexercised');
  assert.equal(health.snapshot().listeners.find(row => row.listener_id === 'task').health, 'disabled');
  assert.equal(health.snapshot().listeners.find(row => row.listener_id === 'editor').health, 'degraded');
});

test('listener health is partial until every required available route is registered', () => {
  const inventory = Object.fromEntries(LISTENER_IDS.map(id => [id, { available: true, enabled: true }]));
  const health = new ListenerHealth(inventory);
  health.recordBus({ connected: true, published: 1 });
  assert.equal(health.snapshot().status, 'partial');
  assert.equal(health.snapshot().coverage_complete, false);
  health.markRegistered(inventory);
  assert.equal(health.snapshot().status, 'healthy');
  assert.equal(health.snapshot().coverage_complete, true);
  assert.equal(health.snapshot().listeners.every(row => row.events_recorded === 0), true);
});

test('unsupported host APIs remain visible limitations without blocking available coverage', () => {
  const inventory = Object.fromEntries(LISTENER_IDS.map(id => [id, { available: id !== 'test', enabled: true }]));
  const health = new ListenerHealth(inventory);
  health.recordBus({ connected: true, published: 1 });
  health.markRegistered(inventory);
  const report = health.snapshot();
  assert.equal(report.status, 'healthy');
  assert.equal(report.coverage_complete, true);
  assert.deepEqual(report.incomplete_listener_ids, []);
  assert.ok(report.limitations.some(value => value.startsWith('test:unsupported')));
});

test('listener activity maps to the canonical schema without retaining scope or content', () => {
  let sequence = 0;
  const attestation = buildActivityAttestation({
    listenerId: 'terminal-shell', category: 'terminal', operation: 'terminal.shell-execution', status: 'started',
    effect: 'process', scopeRefs: ['C:/secret/project/file'], metadata: { command: 'do not retain' }
  }, { actorId: 'extension', sessionId: 'session', harness: 'VS Code', accountableOwner: 'owner' }, {
    projectId: 'project', hostId: 'host', now: () => '2026-08-11T12:00:00Z', uuid: () => `uuid-${++sequence}`
  });
  assert.equal(attestation.schema_version, 'px.operation-event/1');
  assert.equal(attestation.route_id, 'extension.vscode-listener');
  assert.equal(attestation.coverage_tier, 'B');
  assert.equal(attestation.payload_retained, false);
  assert.equal(JSON.stringify(attestation).includes('secret'), false);
  assert.equal(JSON.stringify(attestation).includes('do not retain'), false);
  assert.equal(attestation.canonicalEvent.event_id.startsWith('extension-'), true);
  assert.equal(Object.keys(attestation).includes('canonicalEvent'), false);
});

test('command activity remains a Tier-C attestation rather than claiming listener mediation', () => {
  const attestation = buildActivityAttestation({ operation: 'command.run', status: 'succeeded', effect: 'workspace-write' }, { actorId: 'extension', sessionId: 's', harness: 'VS Code', accountableOwner: 'owner' }, { projectId: 'project', now: () => '2026-08-11T12:00:00Z', uuid: () => 'one' });
  assert.equal(attestation.route_id, 'extension.command');
  assert.equal(attestation.coverage_tier, 'C');
});

test('VS Code API event matrix registers and exercises every declared listener route', () => {
  const uri = value => ({ fsPath: `C:/workspace/${value}`, scheme: 'file', toString: () => `file:///C:/workspace/${value}` });
  const events = Object.fromEntries([
    'changeText', 'saveText', 'openText', 'closeText', 'createFiles', 'deleteFiles', 'renameFiles',
    'openTerminal', 'closeTerminal', 'shellStart', 'shellEnd', 'taskStart', 'taskEnd', 'taskProcessEnd',
    'debugStart', 'debugEnd', 'testResults', 'configuration', 'extensions', 'watchCreate', 'watchChange',
    'watchDelete', 'repositoryChange', 'repositoryOpen'
  ].map(name => [name, emitter()]));
  const watcher = {
    onDidCreate: events.watchCreate, onDidChange: events.watchChange, onDidDelete: events.watchDelete,
    dispose() {}
  };
  const repository = {
    rootUri: uri('.'),
    state: {
      onDidChange: events.repositoryChange, HEAD: { name: 'main', commit: 'abc' },
      workingTreeChanges: [{}], indexChanges: [], mergeChanges: []
    }
  };
  const vscode = {
    workspace: {
      onDidChangeTextDocument: events.changeText, onDidSaveTextDocument: events.saveText,
      onDidOpenTextDocument: events.openText, onDidCloseTextDocument: events.closeText,
      onDidCreateFiles: events.createFiles, onDidDeleteFiles: events.deleteFiles,
      onDidRenameFiles: events.renameFiles, createFileSystemWatcher: () => watcher,
      onDidChangeConfiguration: events.configuration
    },
    window: {
      onDidOpenTerminal: events.openTerminal, onDidCloseTerminal: events.closeTerminal,
      onDidStartTerminalShellExecution: events.shellStart, onDidEndTerminalShellExecution: events.shellEnd
    },
    tasks: { onDidStartTask: events.taskStart, onDidEndTask: events.taskEnd, onDidEndTaskProcess: events.taskProcessEnd },
    debug: { onDidStartDebugSession: events.debugStart, onDidTerminateDebugSession: events.debugEnd },
    tests: { onDidChangeTestResults: events.testResults, testResults: [{ completedAt: 5, results: [{}, {}] }] },
    extensions: {
      onDidChange: events.extensions,
      getExtension: id => id === 'vscode.git' ? { isActive: true, exports: { getAPI: () => ({ repositories: [repository], onDidOpenRepository: events.repositoryOpen }) } } : null
    }
  };
  const recorded = [];
  const scheduled = [];
  const schedule = callback => { const entry = { callback, cancelled: false }; scheduled.push(entry); return entry; };
  const cancelSchedule = entry => { if (entry) entry.cancelled = true; };
  const context = { subscriptions: [] };
  const registration = registerActivityListeners({
    vscode, context, settings: () => ({ activity: {
      captureFileEvents: true, captureTerminalLifecycle: true, captureTaskLifecycle: true,
      captureDebugLifecycle: true, captureTestLifecycle: true, captureCommandText: false
    } }), workspaceRoot: () => 'C:/workspace',
    observeActivity: (input, options) => { recorded.push({ input, options }); return { recorded: true }; },
    unknownObserver: source => ({ actorId: `${source}-unattributed` }),
    excludedActivityPath: () => false, relativeScope: value => value.fsPath,
    schedule, cancelSchedule, delays: { editor: 1, watcherChange: 1, watcherOther: 1, scm: 1 }
  });

  const document = { uri: uri('source.js'), languageId: 'javascript', version: 2, getText: () => 'private content' };
  events.openText.fire(document);
  events.changeText.fire({ document, contentChanges: [{ text: 'inserted', rangeLength: 3 }] });
  events.saveText.fire(document);
  events.closeText.fire(document);
  events.createFiles.fire({ files: [uri('created.txt')] });
  events.deleteFiles.fire({ files: [uri('deleted.txt')] });
  events.renameFiles.fire({ files: [{ oldUri: uri('old.txt'), newUri: uri('new.txt') }] });
  events.watchCreate.fire(uri('watched-created.txt'));
  events.watchChange.fire(uri('watched-changed.txt'));
  events.watchDelete.fire(uri('watched-deleted.txt'));
  const terminal = { name: 'test terminal', exitStatus: { code: 0, reason: 0 } };
  events.openTerminal.fire(terminal);
  events.closeTerminal.fire(terminal);
  const shellExecution = { commandLine: { value: 'secret-command --token hidden', confidence: 2, isTrusted: true } };
  events.shellStart.fire({ execution: shellExecution, terminal });
  events.shellEnd.fire({ execution: shellExecution, terminal, exitCode: 0 });
  const taskExecution = { task: { name: 'matrix task', source: 'test', scope: { name: 'workspace' } } };
  events.taskStart.fire({ execution: taskExecution });
  events.taskEnd.fire({ execution: taskExecution });
  events.taskProcessEnd.fire({ execution: taskExecution, exitCode: 0 });
  const debugSession = { id: 'debug-1', type: 'node', name: 'matrix debug', workspaceFolder: { name: 'workspace' } };
  events.debugStart.fire(debugSession);
  events.debugEnd.fire(debugSession);
  events.testResults.fire();
  events.repositoryChange.fire();
  events.configuration.fire({ affectsConfiguration: key => key === 'pacifyX' || key === 'pacifyX.activity' });
  events.extensions.fire();
  for (const entry of scheduled) if (!entry.cancelled) entry.callback();

  assert.deepEqual([...new Set(recorded.map(row => row.input.listenerId))].sort(), [...LISTENER_IDS].sort());
  assert.ok(recorded.some(row => row.input.operation === 'editor.document.changed' && row.input.metadata.inserted_bytes === 8));
  assert.ok(recorded.some(row => row.input.operation === 'terminal.shell-execution' && row.input.metadata.command_name === '[disabled]'));
  assert.ok(recorded.some(row => row.input.operation === 'terminal.session' && row.input.status === 'observed' && row.input.metadata.lifecycle === 'opened'));
  assert.equal(JSON.stringify(recorded).includes('secret-command'), false);
  assert.ok(recorded.some(row => row.input.operation === 'scm.repository.changed' && row.options.attributeClaim === false));
  assert.ok(registration.subscriptions.length >= LISTENER_IDS.length);
  registration.dispose();
  assert.equal(registration.subscriptions.length, 0);
});

test('registration remains bounded when optional VS Code APIs are unavailable', () => {
  const observed = [];
  const context = { subscriptions: [] };
  const result = registerActivityListeners({
    vscode: { workspace: {}, window: {}, tasks: {}, debug: {}, tests: {}, extensions: {} },
    context, settings: () => ({ activity: {} }), workspaceRoot: () => 'C:/workspace',
    observeActivity: input => observed.push(input), unknownObserver: () => ({}),
    excludedActivityPath: () => false, relativeScope: () => '.', output: { appendLine() {} }
  });
  assert.deepEqual(observed, []);
  assert.equal(result.subscriptions.length, 0);
  assert.equal(context.subscriptions.length, 0);
  result.dispose();
});

test('listener registration gate is singleton and disposes its registration once', () => {
  const gate = new ListenerRegistrationGate(); let registrations = 0; let disposals = 0;
  const factory = () => { registrations += 1; return { dispose: () => { disposals += 1; } }; };
  assert.equal(gate.start(factory), gate.start(factory));
  assert.equal(registrations, 1);
  gate.dispose(); gate.dispose();
  assert.equal(disposals, 1);
  assert.throws(() => gate.start(factory), /disposed/);
});

test('partial listener registration rolls back every acquired disposable and can retry', () => {
  const sources = [emitter(), emitter(), emitter(), emitter()];
  for (let failAfter = 1; failAfter <= sources.length; failAfter += 1) {
    assert.throws(() => registerActivityListeners({
      vscode: { workspace: {
        onDidChangeTextDocument: sources[0], onDidSaveTextDocument: sources[1],
        onDidOpenTextDocument: sources[2], onDidCloseTextDocument: sources[3]
      }, window: {}, tasks: {}, debug: {}, tests: {}, extensions: {} },
      context: { subscriptions: [] }, settings: () => ({ activity: { captureFileEvents: true } }),
      workspaceRoot: () => 'C:/workspace', observeActivity: () => ({ recorded: true }),
      unknownObserver: () => ({}), excludedActivityPath: () => false, relativeScope: () => '.',
      faultInjector: ({ registered }) => { if (registered === failAfter) throw new Error(`fault-${failAfter}`); }
    }), new RegExp(`fault-${failAfter}`));
    assert.deepEqual(sources.map(source => source.count()), [0, 0, 0, 0]);
  }
  const gate = new ListenerRegistrationGate();
  assert.throws(() => gate.start(() => { throw new Error('first-attempt'); }), /first-attempt/);
  const registration = gate.start(() => ({ dispose() {} }));
  assert.equal(typeof registration.dispose, 'function');
  gate.dispose();
});

test('filesystem watcher storms use one timer and bounded aggregate metadata', () => {
  const changed = emitter();
  const watcher = { onDidCreate: emitter(), onDidChange: changed, onDidDelete: emitter(), dispose() {} };
  const scheduled = []; const cancelled = [];
  const schedule = callback => { const token = { callback }; scheduled.push(token); return token; };
  const observed = [];
  const result = registerActivityListeners({
    vscode: { RelativePattern: class RelativePattern { constructor(base, pattern) { this.base = base; this.pattern = pattern; } }, workspace: { createFileSystemWatcher: pattern => { assert.equal(pattern.pattern, '**/{src,runtime,tests,extension,registry,contracts,docs}/**'); return watcher; } }, window: {}, tasks: {}, debug: {}, tests: {}, extensions: {} },
    context: { subscriptions: [] }, settings: () => ({ activity: { captureFileEvents: true } }),
    workspaceRoot: () => 'C:/workspace', observeActivity: (input, options) => { observed.push({ input, options }); return { recorded: true }; },
    unknownObserver: () => ({}), excludedActivityPath: () => false,
    relativeScope: uri => uri.fsPath, schedule, cancelSchedule: token => { if (token) cancelled.push(token); },
    delays: { editor: 1, watcherChange: 1, watcherOther: 1, scm: 1 }
  });
  for (let index = 0; index < MAX_PENDING_WATCHER_PATHS * 4; index += 1) {
    changed.fire({ fsPath: `C:/workspace/generated/${index}.js`, scheme: 'file', toString: () => `file:${index}` });
  }
  assert.equal(scheduled.length, 1, 'one leading-edge timer serves the entire watcher burst');
  scheduled[0].callback();
  assert.equal(observed.length, 1);
  assert.equal(observed[0].input.metadata.event_count, MAX_PENDING_WATCHER_PATHS);
  assert.equal(observed[0].input.metadata.overflow_events, MAX_PENDING_WATCHER_PATHS * 3);
  assert.equal(observed[0].input.scopeRefs.length, MAX_WATCHER_SCOPE_REFS);
  assert.equal(observed[0].input.metadata.scope_refs_capped, true);
  result.dispose();
});

test('proposed test APIs that throw on property access degrade without breaking activation', () => {
  const tests = {}; Object.defineProperty(tests, 'onDidChangeTestResults', { get() { throw new Error('proposed API denied'); } });
  const vscode = { workspace: {}, window: {}, tasks: {}, debug: {}, tests, extensions: {} };
  const inventory = listenerApiInventory(vscode, { activity: {} });
  assert.equal(inventory.test.available, false);
  assert.doesNotThrow(() => registerActivityListeners({
    vscode, context: { subscriptions: [] }, settings: () => ({ activity: {} }), workspaceRoot: () => 'C:/workspace',
    observeActivity: () => ({ recorded: true }), unknownObserver: () => ({}), excludedActivityPath: () => false, relativeScope: () => '.', output: { appendLine() {} }
  }));
});
