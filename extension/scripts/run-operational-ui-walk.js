'use strict';

// Walk the real VS Code workbench and extension webviews over an explicitly
// launched Chromium debugging endpoint. This is an operational inspection
// tool: it does not substitute fixtures, mutate PX records, or issue lifecycle
// actions from the dashboard.

const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const { chromium } = require('playwright-core');
const {
  LIVE_WALK_AUTHORITY,
  buildPerControlRecords,
  loadOperationalSurfaceInventory
} = require('./operational-ui-control-records');
const { evaluateOperationalWalk, exitCodeForTerminalState } = require('./operational-walk-status');

const endpoint = process.argv[2] || 'http://127.0.0.1:9333';
const outputRoot = path.resolve(process.argv[3] || path.join(__dirname, '..', 'evidence', 'operational-ui-walk'));
const inventoryPath = path.resolve(__dirname, '..', '..', 'registry', 'operational_surface_inventory.json');
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function safeScreenshot(locator, target, context, hostErrors) {
  try {
    await locator.screenshot({ path: target, animations: 'disabled', timeout: 5_000 });
    return { status: 'captured', path: path.basename(target) };
  } catch (error) {
    const message = String(error?.message || error).slice(0, 1000);
    hostErrors.push({ source: 'screenshot', context, message });
    return { status: 'failed', path: path.basename(target), error: message };
  }
}

async function allPages(browser) {
  return browser.contexts().flatMap(context => context.pages());
}

async function allDocuments(browser) {
  const documents = [];
  for (const page of await allPages(browser)) {
    documents.push(page);
    for (const frame of page.frames()) if (frame !== page.mainFrame()) documents.push(frame);
  }
  return documents;
}

async function pageText(page) {
  try { return await page.locator('body').innerText({ timeout: 2000 }); } catch { return ''; }
}

async function waitForPage(browser, predicate, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const page of await allPages(browser)) {
      try { if (await predicate(page)) return page; } catch { /* target can reload */ }
    }
    await wait(250);
  }
  return null;
}

async function waitForDocument(browser, predicate, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const document of await allDocuments(browser)) {
      try { if (await predicate(document)) return document; } catch { /* webviews can reload */ }
    }
    await wait(250);
  }
  return null;
}

async function innerText(frameHost) {
  return frameHost.evaluate(frame => String(frame.contentDocument?.body?.innerText || ''));
}

async function waitForOwnedWebview(workbench, predicate, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const shells = workbench.locator('iframe.webview[src*="extensionId=mountain-nomad-bc.pacify-x-vscode"]');
    for (let index = 0; index < await shells.count(); index += 1) {
      const frameHost = shells.nth(index).contentFrame().locator('iframe#active-frame');
      try { if (await predicate(await innerText(frameHost))) return frameHost; } catch { /* iframe can rematerialize */ }
    }
    await wait(250);
  }
  return null;
}

async function executeWorkbenchCommand(workbench, title) {
  await workbench.keyboard.press(process.platform === 'darwin' ? 'Meta+Shift+P' : 'Control+Shift+P');
  const widget = workbench.locator('.quick-input-widget:visible').first();
  await widget.waitFor({ state: 'visible', timeout: 15_000 });
  const input = widget.locator('input').first();
  await input.fill(title);
  const exact = widget.getByText(title, { exact: true }).first();
  try {
    await exact.waitFor({ state: 'visible', timeout: 30_000 });
  } catch {
    const visible = (await widget.innerText()).slice(0, 2000);
    throw new Error(`workbench-command-unavailable:${title}:${visible}`);
  }
  await exact.click();
}

async function inspectSurface(frameHost, surface) {
  const preNavigationScrollTop = await frameHost.evaluate((frame, activeSurface) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable.');
    document.querySelector('[data-action="closeModal"]')?.click();
    document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
    const before = Number(document.scrollingElement.scrollTop || 0);
    let control = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"]`);
    if (!control && ['knowledgeCore', 'runtimeCore'].includes(activeSurface)) {
      document.querySelector('[data-action="toggleAdvanced"]')?.click();
      control = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"]`);
    }
    if (!control) throw new Error(`PX surface is missing: ${activeSurface}`);
    control.click();
    return before;
  }, surface);
  await wait(700);
  if (surface === 'knowledgeGraph') {
    const started = Date.now();
    while (Date.now() - started < 30_000) {
      try {
        if (await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.graph-canvas, .graph-error')))) break;
      } catch { /* receipt records the resulting state */ }
      await wait(250);
    }
  }
  return frameHost.evaluate((frame, activeSurface) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable.');
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const shell = document.querySelector('[data-app-shell]') || document.body;
    const active = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"][aria-current="page"]`) || document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"].active`);
    const expectedHeading = ({ knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core' })[activeSurface];
    const semanticActive = Boolean(expectedHeading && [...shell.querySelectorAll('h1')].some(item => item.textContent.trim() === expectedHeading));
    const actions = [...document.querySelectorAll('[data-action]')].filter(visible).map(item => ({
      action: item.dataset.action,
      label: String(item.innerText || item.getAttribute('aria-label') || '').trim().slice(0, 160),
      disabled: Boolean(item.disabled),
      dataset: Object.fromEntries(Object.entries(item.dataset).map(([key, value]) => [key, String(value).slice(0, 240)]))
    }));
    const overflows = [...document.querySelectorAll('header,nav,main,section,aside,article,button,output')].filter(visible).filter(item => item.scrollWidth > item.clientWidth + 3 || item.scrollHeight > item.clientHeight + 3).slice(0, 80).map(item => ({
      tag: item.tagName.toLowerCase(),
      class: String(item.className || '').slice(0, 160),
      text: String(item.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 180),
      client: [item.clientWidth, item.clientHeight], scroll: [item.scrollWidth, item.scrollHeight]
    }));
    const text = String(shell.innerText || '').trim();
    const graphCanvas = activeSurface === 'knowledgeGraph' ? document.querySelector('[data-graph-canvas]') : null;
    const graphCanvasRect = graphCanvas?.getBoundingClientRect();
    const graphNodes = graphCanvas ? [...graphCanvas.querySelectorAll('.graph-node.actual')] : [];
    const graphNodeRects = graphNodes.map(node => {
      const rect = node.getBoundingClientRect();
      return { key: node.dataset.nodeKey, selected: node.classList.contains('selected'), left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) };
    });
    const graphVisibleNodes = graphCanvasRect ? graphNodeRects.filter(rect => rect.width > 0 && rect.height > 0 && rect.left + rect.width > graphCanvasRect.left && rect.left < graphCanvasRect.right && rect.top + rect.height > graphCanvasRect.top && rect.top < graphCanvasRect.bottom) : [];
    return {
      surface: activeSurface,
      navigation_active: Boolean(active) || semanticActive,
      navigation_evidence: active ? 'active navigation control' : semanticActive ? 'exact advanced-surface heading after direct navigation' : 'not established',
      navigation_scroll_top: Number(document.scrollingElement.scrollTop || 0),
      navigation_at_top: Number(document.scrollingElement.scrollTop || 0) === 0,
      headings: [...shell.querySelectorAll('h1,h2,h3')].filter(visible).map(item => item.innerText.trim()).slice(0, 30),
      visible_actions: actions,
      visible_action_count: actions.length,
      visible_panel_count: [...shell.querySelectorAll('section,article,aside')].filter(visible).length,
      text_characters: text.length,
      provider_missing_message: /There is no data provider registered/i.test(text),
      invalid_union_message: /sidebar-inbound-message-invalid:type:invalid_union/i.test(text),
      operational_error_messages: [...shell.querySelectorAll('[role="alert"],.error,.failed')].filter(visible).map(item => String(item.innerText || '').trim().slice(0, 500)).filter(Boolean).slice(0, 30),
      overflow_candidates: overflows,
      graph: graphCanvas ? {
        canvas: { width: Math.round(graphCanvasRect.width), height: Math.round(graphCanvasRect.height) },
        scene_transform: graphCanvas.querySelector('[data-graph-scene]')?.style.transform || '',
        node_count: graphNodes.length,
        edge_count: graphCanvas.querySelectorAll('.graph-edge-group path').length,
        visible_node_count: graphVisibleNodes.length,
        selected_visible: graphVisibleNodes.some(node => node.selected),
        sample_visible_nodes: graphVisibleNodes.slice(0, 12)
      } : null
    };
  }, surface).then(result => ({ ...result, pre_navigation_scroll_top: preNavigationScrollTop }));
}

function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

async function builderState(frameHost, kind) {
  return frameHost.evaluate((frame, builderKind) => {
    const document = frame.contentDocument;
    const modal = document?.querySelector('.studio-modal');
    const values = selector => [...(modal?.querySelectorAll(selector) || [])].map(element => ({
      action: element.dataset.action || null,
      id: element.dataset.agentNodeId || element.dataset.nodeId || element.dataset.index || null,
      kind: element.dataset.agentKind || element.dataset.nodeTemplate || element.dataset.direction || null,
      value: 'value' in element ? String(element.value).slice(0, 400) : null,
      selected: element.classList.contains('selected') || element.getAttribute('aria-selected') === 'true',
      disabled: Boolean(element.disabled)
    }));
    return {
      builder: builderKind,
      modal_present: Boolean(modal),
      title: modal?.querySelector('h2')?.textContent?.trim() || '',
      visible_tab: modal?.querySelector('[data-action="studioEditorTab"][aria-selected="true"]')?.dataset.tab || null,
      validation: modal?.querySelector('[data-studio-validation]')?.textContent?.trim().replace(/\s+/g, ' ').slice(0, 1200) || '',
      save_disabled: Boolean(modal?.querySelector('[data-action="submitStudioDraft"]')?.disabled),
      agent_sections: values('[data-action="agentSelectSection"]'),
      agent_nodes: values('[data-agent-node-id]'),
      agent_bindings: values('[data-agent-binding-index]'),
      agent_grants: values('[data-agent-grant-index]'),
      workflow_nodes: values('.workflow-editor-node'),
      workflow_ports: values('.workflow-port-handle'),
      workflow_edges: values('[data-action="workflowRemoveEdge"]'),
      agent_scale: modal?.querySelector('[data-agent-editor-canvas]')?.dataset.agentScale || null,
      workflow_scale: modal?.querySelector('[data-workflow-editor-canvas]')?.dataset.workflowScale || null,
      canonical_json: String(modal?.querySelector('#studio-draft-json')?.value || '').slice(0, 200_000)
    };
  }, kind);
}

async function invokeBuilderControl(frameHost, kind, controlId, action, dataset = {}, pick = 'only') {
  const before = await builderState(frameHost, kind);
  const invoked = await frameHost.evaluate((frame, input) => {
    const document = frame.contentDocument;
    const matches = [...document.querySelectorAll(`[data-action="${CSS.escape(input.action)}"]`)].filter(element =>
      Object.entries(input.dataset).every(([key, value]) => String(element.dataset[key] || '') === String(value))
    );
    if (!matches.length) throw new Error(`${input.controlId}: rendered control is missing`);
    const control = input.pick === 'last' ? matches.at(-1) : matches[0];
    if (input.pick === 'only' && matches.length !== 1) throw new Error(`${input.controlId}: expected one rendered control, found ${matches.length}`);
    if (control.disabled) throw new Error(`${input.controlId}: rendered control is disabled`);
    control.click();
    return { match_count: matches.length, label: String(control.innerText || control.getAttribute('aria-label') || '').trim().slice(0, 240) };
  }, { controlId, action, dataset, pick });
  await wait(180);
  const after = await builderState(frameHost, kind);
  return {
    control_id: controlId,
    action,
    dataset,
    invoked,
    before_state_sha256: digest(before),
    after_state_sha256: digest(after),
    changed: digest(before) !== digest(after),
    before,
    after,
    observed_effects: ['bounded unsaved webview draft interaction; no save, host message, workspace write, or runtime execution']
  };
}

async function inspectStudioBuilder(frameHost, kind, outputRoot, hostErrors) {
  const surface = kind === 'agent' ? 'agents' : 'workflows';
  const studioSurface = kind === 'agent' ? 'agent-studio' : 'workflow-studio';
  const observations = [];
  await frameHost.evaluate((frame, values) => {
    const document = frame.contentDocument;
    document.querySelector('[data-action="closeModal"]')?.click();
    document.querySelector(`[data-surface="${CSS.escape(values.surface)}"]`)?.click();
  }, { surface });
  await wait(500);
  const catalogBefore = await builderState(frameHost, kind);
  await frameHost.evaluate((frame, builderKind) => {
    const document = frame.contentDocument;
    const open = [...document.querySelectorAll('[data-action="openStudioDraft"]')].find(button => button.dataset.kind === builderKind);
    if (!open) throw new Error(`${builderKind} Studio create control is missing.`);
    open.click();
  }, kind);
  await wait(500);
  const opened = await builderState(frameHost, kind);
  if (!opened.modal_present) throw new Error(`${kind} Studio modal did not open.`);
  observations.push({
    control_id: `pxui.${surface}.action.openStudioDraft.${kind}`,
    action: 'openStudioDraft', dataset: { kind }, invoked: { match_count: 1, label: `Create ${kind}` },
    before_state_sha256: digest(catalogBefore), after_state_sha256: digest(opened), changed: true,
    before: catalogBefore, after: opened,
    observed_effects: ['opened a new unsaved Studio draft; no host message, workspace write, or runtime execution']
  });
  const plan = kind === 'agent' ? [
    [`pxui.${studioSurface}.action.agentSelectNode.model`, 'agentSelectNode', { agentKind: 'model' }],
    [`pxui.${studioSurface}.action.agentAddTopologyNode.tools`, 'agentAddTopologyNode', { agentKind: 'tools' }],
    [`pxui.${studioSurface}.action.agentRemoveTopologyNode.row`, 'agentRemoveTopologyNode', { agentNodeId: 'agent-node:tools' }],
    [`pxui.${studioSurface}.action.agentAddBinding`, 'agentAddBinding', {}],
    [`pxui.${studioSurface}.action.agentRemoveBinding.row`, 'agentRemoveBinding', {}, 'last'],
    [`pxui.${studioSurface}.action.agentAddGrant`, 'agentAddGrant', {}],
    [`pxui.${studioSurface}.action.agentRemoveGrant.row`, 'agentRemoveGrant', {}, 'last'],
    [`pxui.${studioSurface}.action.agentZoom.in`, 'agentZoom', { delta: '0.1' }],
    [`pxui.${studioSurface}.action.agentAutoLayout`, 'agentAutoLayout', {}],
    [`pxui.${studioSurface}.action.agentFit.toolbar`, 'agentFit', {}, 'first'],
    [`pxui.${studioSurface}.action.studioEditorTab.json`, 'studioEditorTab', { tab: 'json' }],
    [`pxui.${studioSurface}.action.studioEditorTab.visual`, 'studioEditorTab', { tab: 'visual' }]
  ] : [
    [`pxui.${studioSurface}.action.workflowAddNode.task`, 'workflowAddNode', { nodeTemplate: 'task' }],
    [`pxui.${studioSurface}.action.workflowAddPort.inputs`, 'workflowAddPort', { direction: 'inputs' }],
    [`pxui.${studioSurface}.action.workflowAddPort.outputs`, 'workflowAddPort', { direction: 'outputs' }],
    [`pxui.${studioSurface}.action.workflowZoom.in`, 'workflowZoom', { delta: '0.1' }],
    [`pxui.${studioSurface}.action.workflowAutoLayout`, 'workflowAutoLayout', {}],
    [`pxui.${studioSurface}.action.workflowFit`, 'workflowFit', {}],
    [`pxui.${studioSurface}.action.studioEditorTab.json`, 'studioEditorTab', { tab: 'json' }],
    [`pxui.${studioSurface}.action.studioEditorTab.visual`, 'studioEditorTab', { tab: 'visual' }]
  ];
  for (const [controlId, action, dataset, pick = 'only'] of plan) {
    observations.push(await invokeBuilderControl(frameHost, kind, controlId, action, dataset, pick));
  }
  const before = opened;
  const after = await builderState(frameHost, kind);
  if (kind === 'agent') await frameHost.evaluate(frame => { const body = frame.contentDocument?.querySelector('.studio-modal .modal-body'); if (body) body.scrollTop = 0; });
  await wait(150);
  const screenshot = await safeScreenshot(frameHost, path.join(outputRoot, `builder-${kind}.png`), `builder:${kind}`, hostErrors);
  const closeBefore = await builderState(frameHost, kind);
  await frameHost.evaluate(frame => frame.contentDocument.querySelector('.studio-modal [data-action="closeModal"]')?.click());
  await wait(180);
  const closeAfter = await builderState(frameHost, kind);
  observations.push({
    control_id: `pxui.${studioSurface}.action.closeModal`, action: 'closeModal', dataset: {}, invoked: { match_count: 1, label: 'Cancel' },
    before_state_sha256: digest(closeBefore), after_state_sha256: digest(closeAfter), changed: digest(closeBefore) !== digest(closeAfter),
    before: closeBefore, after: closeAfter,
    observed_effects: ['closed the unsaved modal; no candidate was saved or executed']
  });
  return {
    terminal_disposition: 'interaction_complete',
    authority: LIVE_WALK_AUTHORITY,
    before, after, screenshot, observations,
    attempted_control_ids: observations.map(item => item.control_id),
    cleanup: { modal_closed: !closeAfter.modal_present, candidate_saved: false, runtime_executed: false }
  };
}

function applyBuilderObservations(controlChains, builders) {
  const observations = Object.values(builders).flatMap(builder => builder?.observations || []);
  const byId = new Map(controlChains.controls.map(control => [control.control_id, control]));
  for (const observation of observations) {
    const record = byId.get(observation.control_id);
    if (!record) throw new Error(`Builder observed an unregistered control: ${observation.control_id}`);
    record.attempted = true;
    record.rendered = true;
    record.visible = true;
    record.enabled = true;
    record.resolver = { type: 'exact_builder_control', status: 'exact', match_count: observation.invoked.match_count };
    record.before_state_sha256 = observation.before_state_sha256;
    record.after_state_sha256 = observation.after_state_sha256;
    record.observed_effects = observation.observed_effects;
    record.screenshot_references = [builders.agent?.screenshot, builders.workflow?.screenshot].filter(item => item?.status === 'captured').map(item => item.path);
    record.terminal_disposition = 'reversible_ui_interaction_observed';
    record.stages = record.stages.map(stage => {
      if (['open_load', 'display', 'user_edit_action', 'input_validation', 'result_acknowledgement'].includes(stage.stage)) {
        return { stage: stage.stage, status: 'observed', observed_at: record.observed_at, evidence: `${observation.control_id} exact pre/post state digest` };
      }
      if (['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'persistence'].includes(stage.stage)) {
        return { stage: stage.stage, status: 'not_applicable', observed_at: record.observed_at, reason: 'This exact pass is confined to unsaved webview draft state and dispatches no host or durable effect.' };
      }
      return { ...stage, reason: 'Durable reload, injected failure, and recovery behavior is owned by PX-OS-848.' };
    });
  }
  const terminalDispositions = {};
  for (const record of controlChains.controls) terminalDispositions[record.terminal_disposition] = (terminalDispositions[record.terminal_disposition] || 0) + 1;
  controlChains.aggregates.terminal_dispositions = terminalDispositions;
  controlChains.aggregates.attempted_control_count = controlChains.controls.filter(control => control.attempted).length;
  controlChains.builder_observations = observations.map(observation => ({
    control_id: observation.control_id,
    before_state_sha256: observation.before_state_sha256,
    after_state_sha256: observation.after_state_sha256,
    changed: observation.changed,
    observed_effects: observation.observed_effects
  }));
  return controlChains;
}

async function main() {
  // The authoritative denominator is validated before attaching to or
  // interacting with a live host. A changed/duplicate inventory fails closed.
  const inventory = loadOperationalSurfaceInventory(inventoryPath);
  fs.mkdirSync(outputRoot, { recursive: true });
  const browser = await chromium.connectOverCDP(endpoint);
  const hostErrors = [];
  try {
    for (const page of await allPages(browser)) {
      page.on('pageerror', error => hostErrors.push({ source: 'pageerror', message: String(error?.message || error).slice(0, 1000) }));
      page.on('console', message => { if (message.type() === 'error') hostErrors.push({ source: 'console', message: message.text().slice(0, 1000) }); });
    }
    const workbench = await waitForPage(browser, async page => {
      const title = await page.title();
      return /Visual Studio Code|Pacify-X/i.test(title) && !page.url().startsWith('vscode-webview:');
    }, 30_000);
    if (!workbench) throw new Error('VS Code workbench target was not found.');
    await workbench.bringToFront();
    const dashboardTab = workbench.locator('[role="tab"]', { hasText: /PX.*Control Plane/i }).first();
    if (!await dashboardTab.isVisible().catch(() => false)) {
      await executeWorkbenchCommand(workbench, 'Pacify-X: Open Control Plane');
    }
    // Another eager extension can steal editor focus while the command is
    // activating. Select the exact PX tab before VS Code materializes its
    // non-retained webview iframe, and keep failure specificity if it is absent.
    await dashboardTab.waitFor({ state: 'visible', timeout: 30_000 });
    await dashboardTab.click();

    const dashboard = await waitForOwnedWebview(workbench, text => /PACIFY-X\s*\/\s*DASHBOARD/i.test(text), 90_000);
    if (!dashboard) throw new Error('The installed extension did not produce the Pacify-X dashboard webview.');
    const attemptedControlIds = ['pxui.dashboard-control-plane.command.pacifyX.openDashboard'];
    const initialDashboardText = await innerText(dashboard);
    const hostSourceMismatch = /EXTENSION IDENTITY MISMATCH|host-assets-differ-from-source/i.test(initialDashboardText);
    const hostSourceIdentityVerified = !hostSourceMismatch && /exact host\/source identity/i.test(initialDashboardText);
    if (!hostSourceMismatch) {
      const toggledAdvanced = await dashboard.evaluate(frame => {
        const document = frame.contentDocument;
        const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
        if (toggle && toggle.getAttribute('aria-expanded') !== 'true') { toggle.click(); return true; }
        return false;
      });
      if (toggledAdvanced) attemptedControlIds.push('pxui.dashboard-control-plane.action.toggleAdvanced');
      await wait(150);
    }
    const surfaces = await dashboard.evaluate(frame => [...new Set([...frame.contentDocument.querySelectorAll('[data-surface]')].map(item => item.dataset.surface).filter(Boolean))]);
    const results = [];
    if (!hostSourceMismatch) {
      for (const surface of surfaces) {
        const result = await inspectSurface(dashboard, surface);
        attemptedControlIds.push(`pxui.dashboard-control-plane.action.navigate.${surface}`);
        result.screenshot = await safeScreenshot(dashboard, path.join(outputRoot, `${String(results.length + 1).padStart(2, '0')}-${surface}.png`), `surface:${surface}`, hostErrors);
        results.push(result);
        if (surface === 'knowledgeGraph') {
          try {
            await dashboard.evaluate(frame => frame.contentDocument?.querySelector('[data-graph-canvas]')?.scrollIntoView({ block: 'center' }));
            await wait(300);
            result.graph_screenshot = await safeScreenshot(dashboard, path.join(outputRoot, 'knowledge-graph-canvas.png'), 'knowledge-graph-canvas', hostErrors);
          }
          catch (error) { hostErrors.push({ source: 'walker', message: `knowledge graph canvas screenshot failed: ${String(error?.message || error).slice(0, 800)}` }); }
        }
      }
    }
    const builders = {};
    for (const kind of ['agent', 'workflow']) {
      if (hostSourceMismatch) {
        builders[kind] = { terminal_disposition: 'blocked_host_source_mismatch', reason: 'No builder interaction is allowed against installed assets that differ from source.' };
        continue;
      }
      try { builders[kind] = await inspectStudioBuilder(dashboard, kind, outputRoot, hostErrors); }
      catch (error) {
        const message = String(error?.message || error).slice(0, 1000);
        hostErrors.push({ source: 'walker', context: `${kind}-builder`, message });
        await dashboard.evaluate(frame => frame.contentDocument?.querySelector('.studio-modal [data-action="closeModal"]')?.click()).catch(() => {});
        builders[kind] = { terminal_disposition: 'failed', reason: message, observations: [], attempted_control_ids: [] };
      }
    }
    let sidebarOpenError = null;
    const isSidebarText = text => /PACIFY-X[\s\S]*OPEN CONTROL PLANE/i.test(text) && /NO ACTIVE EXECUTION|PROVIDER ACTIVITY/i.test(text);
    let sidebar = await waitForOwnedWebview(workbench, isSidebarText, 1_500);
    const activityControl = workbench.locator('.activitybar [aria-label="Pacify-X"]:visible').first();
    if (!hostSourceMismatch && !sidebar && await activityControl.count()) await activityControl.click({ timeout: 3000 });
    else if (!hostSourceMismatch && !sidebar) {
      // VS Code moves extension containers into Additional Views when the
      // activity bar is full. Select the real contributed view from that menu.
      try {
        await workbench.locator('.activitybar .codicon-more').click({ timeout: 3000 });
        const overflowItem = workbench.getByRole('menuitemcheckbox', { name: 'Pacify-X' });
        await overflowItem.waitFor({ state: 'visible', timeout: 3000 });
        await overflowItem.click({ timeout: 3000 });
        // The overflow menu controls whether the activity item is pinned; it
        // does not consistently open the contributed container. Activate the
        // now-visible item explicitly.
        await workbench.locator('.activitybar [aria-label="Pacify-X"]:visible').click({ timeout: 3000 });
      } catch (error) { sidebarOpenError = String(error?.message || error).slice(0, 500); }
    }
    if (!hostSourceMismatch && !sidebar) sidebar = await waitForOwnedWebview(workbench, isSidebarText, 15_000);
    const sidebarResult = sidebar ? {
      text: (await innerText(sidebar)).slice(0, 20_000),
      provider_missing_message: /There is no data provider registered/i.test(await innerText(sidebar)),
      invalid_union_message: /sidebar-inbound-message-invalid:type:invalid_union/i.test(await innerText(sidebar)),
      buttons: await sidebar.evaluate(frame => [...frame.contentDocument.querySelectorAll('button')].filter(item => {
        const rect = item.getBoundingClientRect(); return rect.width > 0 && rect.height > 0;
      }).map(item => ({
        label: String(item.innerText || item.getAttribute('aria-label') || '').trim(),
        disabled: Boolean(item.disabled),
        action: item.dataset.action || null,
        dataset: Object.fromEntries(Object.entries(item.dataset).map(([key, value]) => [key, String(value).slice(0, 240)]))
      })))
    } : null;
    const sidebarScreenshot = sidebar ? await safeScreenshot(sidebar, path.join(outputRoot, 'sidebar.png'), 'sidebar', hostErrors) : null;
    const observedAt = new Date().toISOString();
    const builderControlIds = Object.values(builders).flatMap(builder => builder?.attempted_control_ids || []);
    const controlChains = applyBuilderObservations(buildPerControlRecords({
      inventory,
      results,
      sidebar: sidebarResult,
      hostSourceMismatch,
      authority: LIVE_WALK_AUTHORITY,
      observedAt,
      attemptedControlIds: [...attemptedControlIds, ...builderControlIds]
    }), builders);
    const receipt = {
      schema_version: 'px.operational-ui-walk/1.2',
      observed_at: observedAt,
      endpoint,
      authority: LIVE_WALK_AUTHORITY,
      host_source_mismatch: hostSourceMismatch,
      source_identity: {
        state: hostSourceMismatch ? 'mismatch' : hostSourceIdentityVerified ? 'verified' : 'unknown',
        method: 'dashboard-runtime-identity-contract'
      },
      surfaces,
      results,
      builders,
      sidebar: sidebarResult,
      sidebar_screenshot: sidebarScreenshot,
      sidebar_open_error: sidebarOpenError,
      host_errors: hostErrors,
      control_chains: controlChains,
      limitations: [
        'The inventory denominator is authoritative; every inventory control receives exactly one terminal record with all thirteen chain stages.',
        hostSourceMismatch ? 'Installed/source identity mismatch blocked all further surface and builder interaction.' : 'The walk activates every dashboard navigation surface and records its real DOM and screenshots.',
        'Agent and Workflow builder interactions are limited to reversible unsaved webview state with exact per-control pre/post digests; no candidate save or run is authorized.',
        'Controls requiring write, execution, lifecycle, recovery, reload, or destructive authority are skipped per control with an exact reason and return condition.'
      ]
    };
    receipt.status_truth = evaluateOperationalWalk(receipt);
    receipt.status = receipt.status_truth.terminal_state;
    fs.writeFileSync(path.join(outputRoot, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify({ outputRoot, status: receipt.status, operationallyComplete: receipt.status_truth.operationally_complete, statusSummary: receipt.status_truth.summary, surfaces: surfaces.length, sidebar: Boolean(sidebar), hostSourceMismatch, controlChains: controlChains.aggregates, providerMissing: results.some(item => item.provider_missing_message) || sidebarResult?.provider_missing_message === true, invalidUnion: results.some(item => item.invalid_union_message) || sidebarResult?.invalid_union_message === true, graph: results.find(item => item.surface === 'knowledgeGraph')?.graph || null, builders, hostErrors: hostErrors.length }, null, 2)}\n`);
    process.exitCode = exitCodeForTerminalState(receipt.status);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
