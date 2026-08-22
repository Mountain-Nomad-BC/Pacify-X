'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const vscode = require('vscode');

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitFor(predicate, timeoutMs = 12000, intervalMs = 100) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = await predicate();
    if (value) return value;
    await sleep(intervalMs);
  }
  return null;
}

async function run() {
  const receiptPath = process.env.PX_VSCODE_SMOKE_RECEIPT;
  assert.ok(receiptPath, 'PX_VSCODE_SMOKE_RECEIPT is required');
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The smoke test requires one isolated workspace folder');
  const extension = vscode.extensions.getExtension('mountain-nomad-bc.pacify-x-vscode');
  assert.ok(extension, 'Development extension was not discovered');
  await extension.activate();
  const contributedView = extension.packageJSON?.contributes?.views?.pacifyX?.find(item => item.id === 'pacifyX.controlCenter');
  assert.equal(contributedView?.type, 'webview', 'Installed control center must contribute a webview');
  const commands = new Set(await vscode.commands.getCommands(true));
  assert.ok(commands.has('workbench.view.extension.pacifyX'), 'Installed Pacify-X view container command is missing');
  assert.ok(commands.has('pacifyX.controlCenter.focus'), 'Installed Control Center focus command is missing');
  await vscode.commands.executeCommand('workbench.view.extension.pacifyX');
  await vscode.commands.executeCommand('pacifyX.controlCenter.focus');
  const sidebarInspection = await waitFor(async () => {
    const current = await vscode.commands.executeCommand('pacifyX.inspectObservability');
    return current?.sidebar?.resolved && current.sidebar.html_assigned ? current.sidebar : null;
  }, 12000, 100);
  assert.ok(sidebarInspection, 'Installed Control Center never invoked resolveWebviewView or assigned webview HTML');
  assert.ok(sidebarInspection.resolve_count >= 1, 'Installed Control Center did not record a provider resolution');
  await vscode.commands.executeCommand('pacifyX.openDashboard', 'dashboard');
  const liveInspection = await waitFor(async () => {
    const current = await vscode.commands.executeCommand('pacifyX.inspectObservability');
    return current?.snapshot?.connected ? current : null;
  }, 30000, 250);
  assert.ok(liveInspection, 'Installed extension never exposed a connected canonical dashboard snapshot');
  const populatedSidebar = await waitFor(async () => {
    const current = await vscode.commands.executeCommand('pacifyX.inspectObservability');
    const sidebar = current?.sidebar;
    const revision = current?.snapshot?.coordinationData?.state?.revision ?? 0;
    return sidebar?.rendered?.connected && sidebar.rendered.revision === revision && sidebar.rendered.visibleComponentCount >= 4 ? sidebar : null;
  }, 12000, 100);
  assert.ok(populatedSidebar, 'Installed Control Center did not acknowledge a populated canonical sidebar projection at the current revision');
  assert.ok(populatedSidebar.ready_count >= 1, 'Installed sidebar renderer never completed its ready handshake');
  assert.ok(populatedSidebar.render_ack_count >= 1, 'Installed sidebar renderer never acknowledged a rendered snapshot');
  const engineRoot = process.env.PX_ENGINE_ROOT;
  assert.ok(engineRoot, 'PX_ENGINE_ROOT is required for installed runtime certification');
  const canonical = childProcess.spawnSync(process.env.PX_PYTHON_PATH || (process.platform === 'win32' ? 'python' : 'python3'), [
    '-m', 'runtime.dashboard_api', 'snapshot', '--source-root', engineRoot,
    '--project', folder.uri.fsPath
  ], { cwd: engineRoot, encoding: 'utf8', shell: false, windowsHide: true, timeout: 60000 });
  assert.equal(canonical.error, undefined, canonical.error?.message);
  assert.equal(canonical.status, 0, `Canonical dashboard snapshot failed: ${canonical.stderr}`);
  const canonicalSnapshot = JSON.parse(canonical.stdout);
  for (const key of ['skills', 'tools', 'agents', 'orchestrations_total', 'knowledge_sources', 'models', 'graph_records', 'graph_edges', 'contracts', 'tests', 'effects']) {
    assert.equal(liveInspection.snapshot.counts[key], canonicalSnapshot.counts[key], `Installed snapshot cardinality drift: ${key}`);
  }
  assert.equal(path.resolve(liveInspection.snapshot.source.engineRoot), path.resolve(engineRoot));
  const environmentResult = await vscode.commands.executeCommand('pacifyX.certifyEnvironmentPersistence');
  assert.equal(environmentResult?.inventory?.schema_version, 'px.environment-capability-map/2.0');
  assert.equal(environmentResult?.inventory?.boundaries?.credential_values_persisted, false);
  assert.equal(environmentResult?.inventory?.boundaries?.network_installs, false);
  const environmentPath = path.join(folder.uri.fsPath, '.engineering-bootstrap', 'environment', 'current.json');
  assert.equal(fs.existsSync(environmentPath), true, 'Approved installed-host environment discovery did not persist current.json');
  const persistedEnvironment = JSON.parse(fs.readFileSync(environmentPath, 'utf8'));
  assert.equal(persistedEnvironment.snapshot_hash, environmentResult.inventory.snapshot_hash);
  await vscode.commands.executeCommand('pacifyX.openDashboard', '/control-plane/knowledge-graph');
  const liveGraph = await waitFor(async () => {
    const current = await vscode.commands.executeCommand('pacifyX.inspectObservability');
    const graph = current?.dashboard_graph;
    return graph?.node_count > 0 && graph?.edge_count > 0 && graph?.visible_node_count > 0 && graph?.canvas_width > 0 && graph?.canvas_height > 0 ? graph : null;
  }, 30000, 250);
  const lastGraph = (await vscode.commands.executeCommand('pacifyX.inspectObservability'))?.dashboard_graph;
  assert.ok(liveGraph, `Installed dashboard did not acknowledge nonzero live graph geometry; last host stage: ${JSON.stringify(lastGraph)}`);
  assert.equal(liveGraph.view, 'capabilities');

  // Load these boundaries from the exact installed extension, not the source
  // checkout or synthetic preview. This catches stale VSIX protocol copies.
  const installedMessages = require(path.join(extension.extensionPath, 'src', 'webviewMessages.js'));
  const installedBridgeModule = require(path.join(extension.extensionPath, 'src', 'pxBridge.js'));
  const installedStudioBootstrap = require(path.join(extension.extensionPath, 'src', 'studioBootstrap.js'));
  const installedStudioApprovalHost = require(path.join(extension.extensionPath, 'src', 'studioApprovalHost.js'));
  const installedStudioDraftHost = require(path.join(extension.extensionPath, 'src', 'studioDraftHost.js'));
  const installedStudioPackage = require(path.join(extension.extensionPath, 'src', 'studioPackage.js'));
  const protocolCases = [
    { type: 'studioOperation', kind: 'agent', operation: 'start', payload: {} },
    { type: 'studioOperation', requestId: 'installed-smoke:workflow-resume', kind: 'workflow', operation: 'resume', payload: { run_id: 'run:installed-smoke' } },
    { type: 'studioOperation', kind: 'knowledge', operation: 'browse', payload: { query: '', limit: 1 } }
  ];
  for (const message of protocolCases) assert.equal(installedMessages.validateWebviewMessage(message).operation, message.operation);
  const previousStudioKeyRoot = process.env.PX_STUDIO_KEY_ROOT;
  process.env.PX_STUDIO_KEY_ROOT = path.join(path.dirname(folder.uri.fsPath), 'studio-approval-keys');
  const studioApprovalMaterial = installedStudioApprovalHost.generateApprovalKey();
  const installedBridge = new installedBridgeModule.PxBridge({
    pythonPath: process.env.PX_PYTHON_PATH || (process.platform === 'win32' ? 'python' : 'python3'),
    engineRoot,
    projectRoot: folder.uri.fsPath,
    approvalKeyProvider: async request => request?.action === 'find' && request.keyId !== studioApprovalMaterial.keyId
      ? null
      : request?.action === 'find' ? studioApprovalMaterial : { active: studioApprovalMaterial, previous: [] }
  });
  let knowledgeRoundTrip;
  let studioSetup;
  let installedAgent;
  let installedWorkflow;
  let installedSkill;
  let installedSkillOutcome;
  try {
    knowledgeRoundTrip = await installedBridge.studioOperation('knowledge', 'browse', { query: '', limit: 1 });
    studioSetup = await installedStudioBootstrap.setupStudio(installedBridge);
    const agents = await installedBridge.catalog({ kind: 'agents', query: installedStudioBootstrap.STARTER_AGENT.agent_id, status: '', offset: 0, limit: 20, sort: 'id' });
    const workflows = await installedBridge.catalog({ kind: 'workflows', query: installedStudioBootstrap.STARTER_WORKFLOW.workflow_id, status: '', offset: 0, limit: 20, sort: 'id' });
    installedAgent = agents.items.find(item => item.kind === 'studio-agent-revision' && item.details?.agent_id === installedStudioBootstrap.STARTER_AGENT.agent_id && item.details?.version === studioSetup.agent.version);
    installedWorkflow = workflows.items.find(item => item.kind === 'studio-workflow-revision' && item.details?.workflow_id === installedStudioBootstrap.STARTER_WORKFLOW.workflow_id && item.details?.version === studioSetup.workflow.version);
    const skillId = 'skill:pacify-x-installed-starter';
    const skillVersion = '1.0.0';
    const skillPayload = {
      skill_id: skillId, version: skillVersion, owner: 'human:vscode-local-user', builder_domain: 'px-standard',
      triggers: ['explicit installed-host request'], non_triggers: ['unrelated task'], permissions: ['read_local'], effects: ['read'],
      resources: ['resources/README.md'], contracts: ['contracts/input.schema.json'], tests: ['tests/contract.json'],
      provenance: { source: 'installed-vsix-studio-editor' }, lifecycle: 'draft',
      editor_files: {
        'SKILL.md': `---\nname: ${skillId}\ndescription: Installed-host editable Skill Studio round trip.\n---\n\n# Installed Skill Studio\n`,
        'capability.json': `${JSON.stringify({ schema_version: 'px.skill-capability/1.0', id: skillId, version: skillVersion, domain: 'px-standard', effects: ['read'], permissions: ['read_local'], triggers: ['explicit installed-host request'], non_triggers: ['unrelated task'] }, null, 2)}\n`,
        'skill.yaml': `schema_version: px.skill-manifest/1.0\nid: ${skillId}\nversion: ${skillVersion}\nentrypoint: SKILL.md\ndomain: px-standard\n`,
        'contracts/input.schema.json': `${JSON.stringify({ type: 'object', additionalProperties: false, properties: {} }, null, 2)}\n`,
        'tests/contract.json': `${JSON.stringify({ schema_version: 'px.skill-test/1.1', cases: [{ name: 'required-files', assertion: { kind: 'required-files', paths: ['SKILL.md', 'capability.json', 'skill.yaml'] } }] }, null, 2)}\n`,
        'resources/README.md': '# Resources\n\nBounded local resources only.\n'
      }
    };
    installedSkillOutcome = await installedStudioDraftHost.createStudioDraftFromHost({ requestId: 'installed-vsix:skill-save', kind: 'skill', payload: skillPayload }, {
      bridge: installedBridge,
      postMessage: async () => true,
      confirmCreate: async () => true,
      materializeSkillPackage: installedStudioPackage.materializeSkillPackage,
      assertInitialCreateAbsent: (kind, identity) => installedBridge.studioIdentityAbsence(kind, identity),
      reclaimSkillPackage: installedStudioPackage.reclaimMaterializedSkillPackage,
      isVersionConflict: error => Boolean(installedBridgeModule.exactStudioVersionConflictError(error))
    });
    const skills = await installedBridge.catalog({ kind: 'skills', query: skillId, status: '', offset: 0, limit: 20, sort: 'id' });
    installedSkill = skills.items.find(item => item.kind === 'studio-skill-revision' && item.details?.skill_id === skillId);
  } finally {
    installedBridge.dispose();
    if (previousStudioKeyRoot === undefined) delete process.env.PX_STUDIO_KEY_ROOT;
    else process.env.PX_STUDIO_KEY_ROOT = previousStudioKeyRoot;
  }
  assert.equal(knowledgeRoundTrip.schema_version, 'px.knowledge-core-control/1.0');
  assert.equal(studioSetup?.ready, true, 'Installed Studio setup did not complete');
  assert.equal(studioSetup?.agent?.run_outcome, 'succeeded', 'Installed Agent Studio revision did not run');
  assert.equal(studioSetup?.workflow?.run_state, 'succeeded', 'Installed Workflow Studio revision did not run');
  assert.equal(installedAgent?.details?.lifecycle_authentication?.authenticated, true, 'Installed Agent Studio revision did not reopen as authenticated');
  assert.equal(installedAgent?.details?.builder_graph_state, 'content-bound', 'Installed Agent Studio builder state was not retained');
  assert.equal(installedWorkflow?.details?.lifecycle_authentication?.authenticated, true, 'Installed Workflow Studio revision did not reopen as authenticated');
  assert.equal(installedWorkflow?.details?.editor_layout_state, 'content-bound', 'Installed Workflow Studio layout was not retained');
  assert.equal(installedSkillOutcome?.status, 'created', 'Installed Skill Studio editor payload was not saved');
  assert.equal(installedSkill?.details?.lifecycle_authentication?.status, 'candidate', 'Installed Skill Studio revision did not reopen as a candidate');
  assert.equal(installedSkill?.details?.package_scope, 'project-studio', 'Installed Skill Studio revision escaped the project Studio package scope');
  assert.match(String(installedSkill?.details?.source_content_sha256 || ''), /^[a-f0-9]{64}$/, 'Installed Skill Studio content binding is missing');
  const exactStudioRoundTrips = {
    installed_extension_path: '[installed-extension-root]',
    accepted_operations: protocolCases.map(item => `${item.kind}:${item.operation}`),
    knowledge_ui_bridge_cli_backend: true,
    knowledge_schema_version: knowledgeRoundTrip.schema_version,
    setup_ready: studioSetup.ready,
    completed_steps: studioSetup.completed_steps,
    agent: {
      identity: studioSetup.agent.identity,
      admission: studioSetup.agent.decision,
      run_outcome: studioSetup.agent.run_outcome,
      reopen_authenticated: installedAgent.details.lifecycle_authentication.authenticated,
      builder_graph_state: installedAgent.details.builder_graph_state
    },
    workflow: {
      identity: studioSetup.workflow.identity,
      admission: studioSetup.workflow.decision,
      run_state: studioSetup.workflow.run_state,
      reopen_authenticated: installedWorkflow.details.lifecycle_authentication.authenticated,
      editor_layout_state: installedWorkflow.details.editor_layout_state
    },
    skill: {
      identity: installedSkill.details.skill_id,
      save_status: installedSkillOutcome.status,
      lifecycle_status: installedSkill.details.lifecycle_authentication.status,
      package_scope: installedSkill.details.package_scope,
      content_bound: /^[a-f0-9]{64}$/.test(String(installedSkill.details.source_content_sha256 || ''))
    }
  };

  const attempts = {};
  const target = vscode.Uri.joinPath(folder.uri, 'listener-matrix.txt');
  const document = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(document);
  const edit = new vscode.WorkspaceEdit();
  edit.insert(target, new vscode.Position(0, 0), 'editor event\n');
  assert.equal(await vscode.workspace.applyEdit(edit), true);
  assert.equal(await document.save(), true);
  await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
  attempts.editor = 'exercised-live';

  const lifecycle = vscode.Uri.joinPath(folder.uri, 'lifecycle-created.txt');
  const create = new vscode.WorkspaceEdit();
  create.createFile(lifecycle, { overwrite: false, ignoreIfExists: false });
  assert.equal(await vscode.workspace.applyEdit(create), true);
  const renamed = vscode.Uri.joinPath(folder.uri, 'lifecycle-renamed.txt');
  const rename = new vscode.WorkspaceEdit();
  rename.renameFile(lifecycle, renamed, { overwrite: false });
  assert.equal(await vscode.workspace.applyEdit(rename), true);
  const remove = new vscode.WorkspaceEdit();
  remove.deleteFile(renamed, { ignoreIfNotExists: false, recursive: false });
  assert.equal(await vscode.workspace.applyEdit(remove), true);
  attempts.filesystem = 'exercised-live';

  const watchedDirectory = vscode.Uri.joinPath(folder.uri, 'tests');
  await vscode.workspace.fs.createDirectory(watchedDirectory);
  const watched = vscode.Uri.joinPath(watchedDirectory, 'watcher-live.txt');
  await sleep(300);
  fs.writeFileSync(watched.fsPath, 'watcher event\n', 'utf8');
  await sleep(800);
  fs.appendFileSync(watched.fsPath, 'watcher changed\n', 'utf8');
  await sleep(900);
  attempts['filesystem-watcher'] = 'exercised-live';

  const terminal = vscode.window.createTerminal({ name: 'PX O04 live matrix' });
  terminal.show(false);
  attempts.terminal = 'exercised-live';
  const shellReady = await waitFor(() => terminal.shellIntegration, 5000);
  const shellCommand = process.platform === 'win32' ? 'Write-Output' : 'printf';
  const shellArgs = process.platform === 'win32' ? ['px-o04-shell-event'] : ['%s\\n', 'px-o04-shell-event'];
  if (shellReady) {
    const execution = shellReady.executeCommand(shellCommand, shellArgs);
    await waitFor(async () => {
      try { for await (const _chunk of execution.read()) { /* lifecycle only */ } return true; } catch { return false; }
    }, 5000);
    attempts['terminal-shell'] = 'exercised-live';
  } else {
    terminal.sendText(process.platform === 'win32' ? 'Write-Output px-o04-shell-event' : "printf '%s\\n' px-o04-shell-event", true);
    attempts['terminal-shell'] = 'api-available-shell-integration-not-ready';
  }
  await sleep(400);
  terminal.dispose();

  const task = new vscode.Task(
    { type: 'px-o04-smoke' }, folder, 'PX O04 task event', 'Pacify-X tests',
    process.platform === 'win32'
      ? new vscode.ShellExecution('cmd.exe', ['/d', '/c', 'exit', '0'])
      : new vscode.ShellExecution('/bin/sh', ['-c', 'exit 0'])
  );
  const taskDone = new Promise(resolve => {
    const disposable = vscode.tasks.onDidEndTaskProcess(event => {
      if (event.execution.task.name === task.name) { disposable.dispose(); resolve(event.exitCode); }
    });
  });
  await vscode.tasks.executeTask(task);
  assert.equal(await Promise.race([taskDone, sleep(10000).then(() => 'timeout')]), 0);
  attempts.task = 'exercised-live';

  const controller = vscode.tests.createTestController('px-o04-live-matrix', 'PX O04 live matrix');
  const item = controller.createTestItem('listener-result', 'Listener result');
  controller.items.add(item);
  const testRun = controller.createTestRun(new vscode.TestRunRequest([item]));
  testRun.started(item);
  testRun.passed(item, 1);
  testRun.end();
  attempts.test = 'exercised-live';

  const debugProgram = path.join(folder.uri.fsPath, 'debug-live.js');
  fs.writeFileSync(debugProgram, 'setTimeout(() => process.exit(0), 150);\n', 'utf8');
  try {
    const debugStarted = await vscode.debug.startDebugging(folder, { type: 'node', request: 'launch', name: 'PX O04 debug event', program: debugProgram });
    if (debugStarted) {
      await waitFor(() => !vscode.debug.activeDebugSession, 10000);
      attempts.debug = 'exercised-live';
    } else attempts.debug = 'start-returned-false';
  } catch (error) {
    attempts.debug = `unavailable:${error.name}`;
  }

  const configuration = vscode.workspace.getConfiguration('pacifyX');
  const priorRetention = configuration.get('activity.retentionDays');
  await configuration.update('activity.retentionDays', priorRetention === 31 ? 32 : 31, vscode.ConfigurationTarget.Workspace);
  await sleep(200);
  await configuration.update('activity.retentionDays', priorRetention, vscode.ConfigurationTarget.Workspace);
  attempts.configuration = 'exercised-live';

  fs.appendFileSync(target.fsPath, 'scm event\n', 'utf8');
  attempts.scm = 'mutation-issued-live-api-observation-verified-from-ledger';
  attempts.extensions = 'api-available-live-mutation-not-performed; exercised-in-injected-api-matrix';
  await sleep(1800);

  let inspection = await vscode.commands.executeCommand('pacifyX.inspectObservability');
  if (process.env.PX_EXPECT_CANONICAL_BUS === '1') {
    inspection = await waitFor(async () => {
      const current = await vscode.commands.executeCommand('pacifyX.inspectObservability');
      return current?.listeners?.canonical_bus_connected ? current : null;
    }, 20000, 250) || inspection;
  }
  assert.equal(inspection?.schema_version, 'px.vscode-observability-inspection/1.0');
  assert.ok(inspection?.startup?.activation_ms >= 0 && inspection.startup.activation_ms < 500, `Activation exceeded 500ms: ${inspection?.startup?.activation_ms}`);
  assert.equal(inspection.startup.subprocesses_started, 0);
  assert.equal(inspection.startup.discovery_started, false);
  assert.equal(inspection.startup.project_writes, 0);
  assert.equal(inspection?.activity?.integrity?.valid, true);
  const operations = new Set((inspection.activity.events || []).map(event => event.operation));
  const liveExpectations = {
    editor: ['editor.document.opened', 'editor.document.changed', 'editor.document.saved'],
    filesystem: ['workspace.file.created', 'workspace.file.renamed', 'workspace.file.deleted'],
    'filesystem-watcher': ['workspace.file.changed'], terminal: ['terminal.session'],
    task: ['vscode.task', 'vscode.task-process'], test: ['test.result'],
    configuration: ['observability.configuration-changed']
  };
  const verified = {};
  for (const [listenerId, expected] of Object.entries(liveExpectations)) {
    const found = expected.filter(operation => operations.has(operation));
    verified[listenerId] = { expected, found, complete: found.length === expected.length };
  }
  const debugSeen = operations.has('debug.session');
  verified.debug = { expected: ['debug.session'], found: debugSeen ? ['debug.session'] : [], complete: debugSeen };
  const shellSeen = operations.has('terminal.shell-execution');
  verified['terminal-shell'] = { expected: ['terminal.shell-execution'], found: shellSeen ? ['terminal.shell-execution'] : [], complete: shellSeen };
  const scmSeen = operations.has('scm.repository.changed');
  verified.scm = { expected: ['scm.repository.changed'], found: scmSeen ? ['scm.repository.changed'] : [], complete: scmSeen };
  verified.extensions = { expected: ['vscode.extensions.changed'], found: operations.has('vscode.extensions.changed') ? ['vscode.extensions.changed'] : [], complete: operations.has('vscode.extensions.changed') };
  for (const listenerId of ['editor', 'filesystem', 'filesystem-watcher', 'terminal', 'task', 'configuration']) {
    assert.equal(verified[listenerId].complete, true, `live listener did not produce expected operations: ${listenerId}`);
  }
  assert.ok((inspection.listeners.listeners || []).every(row => typeof row.api_available === 'boolean'));
  const extensionsListener = inspection.listeners.listeners.find(row => row.listener_id === 'extensions');
  assert.ok(extensionsListener?.api_available, 'Installed host did not expose the VS Code extensions lifecycle API');
  assert.ok(extensionsListener?.registered, 'Installed extension did not register the extensions lifecycle listener');
  assert.equal(inspection.listeners.coverage_tier, 'B');
  assert.equal(inspection.listeners.canonical_bus_connected, process.env.PX_EXPECT_CANONICAL_BUS === '1');
  let canonicalBusState = null;
  const canonicalBusStatePath = path.join(folder.uri.fsPath, '.engineering-bootstrap', 'operation-bus', 'state.json');
  if (process.env.PX_EXPECT_CANONICAL_BUS === '1') {
    canonicalBusState = JSON.parse(fs.readFileSync(canonicalBusStatePath, 'utf8'));
    assert.ok(canonicalBusState.event_count > 0, 'canonical operational bus must retain published events');
    assert.equal(canonicalBusState.event_count, canonicalBusState.revision);
  }

  const receipt = {
    schema_version: 'px.vscode-host-listener-smoke/1.0',
    vscode_version: vscode.version,
    extension_version: extension.packageJSON.version,
    workspace: '[isolated-temporary-workspace]',
    attempts, verified,
    listener_health: inspection.listeners,
    canonical_bus_state: canonicalBusState,
    activity_integrity: inspection.activity.integrity,
    operation_count: operations.size,
    live_sidebar: {
      container_opened: true,
      focus_command_executed: true,
      contributed_type: contributedView.type,
      provider: populatedSidebar
    },
    live_dashboard: {
      opened: true,
      startup: inspection.startup,
      connected: liveInspection.snapshot.connected,
      source: liveInspection.snapshot.source,
      counts: liveInspection.snapshot.counts,
      canonical_counts_match: true,
      cache: liveInspection.snapshot.cache,
      efficiency: liveInspection.efficiency
    },
    live_knowledge_graph: liveGraph,
    approved_environment_persistence: {
      current_path: '.engineering-bootstrap/environment/current.json',
      snapshot_hash: persistedEnvironment.snapshot_hash,
      generation: persistedEnvironment.discovery?.generation,
      credential_values_persisted: persistedEnvironment.boundaries?.credential_values_persisted
    },
    exact_studio_round_trips: exactStudioRoundTrips,
    limitations: [
      'Extension installation or enablement was not mutated in the live host; the extensions event is covered by the injected VS Code API matrix.',
      'Terminal shell integration, debug-adapter startup, and built-in Git activation are host-dependent; their exact live results are reported without promotion.',
      inspection.listeners.canonical_bus_connected ? 'Listener events were batch-published to the canonical Python operational bus.' : 'Canonical-bus publication was not configured for this host run; project activity attestations remain available.'
    ]
  };
  fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  controller.dispose();
}

module.exports = { run };
