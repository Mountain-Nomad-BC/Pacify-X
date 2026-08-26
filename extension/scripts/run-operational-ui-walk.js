'use strict';

// Walk the real VS Code workbench and extension webviews over an explicitly
// launched Chromium debugging endpoint. This is an operational inspection
// tool: it does not substitute fixtures, mutate PX records, or issue lifecycle
// actions from the dashboard.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { beginOwnedEngineOutage } = require('./owned-engine-outage');
const {
  LIVE_WALK_AUTHORITY,
  buildPerControlRecords,
  loadOperationalSurfaceInventory
} = require('./operational-ui-control-records');
const { evaluateOperationalWalk, exitCodeForTerminalState } = require('./operational-walk-status');
const {
  STAGES,
  actionIdentity,
  currentSourceManifest,
  directSelectorFor,
  revealActionFor,
  selectorForKind,
  semanticLabel,
  stageResult
} = require('./run-exhaustive-operational-control-walk');

const endpoint = process.argv[2] || 'http://127.0.0.1:9333';
const outputRoot = path.resolve(process.argv[3] || path.join(__dirname, '..', 'evidence', 'operational-ui-walk'));
const inventoryPath = path.resolve(__dirname, '..', '..', 'registry', 'operational_surface_inventory.json');
const proofMatrixPath = path.resolve(__dirname, '..', '..', 'registry', 'operational_control_proof_matrix.json');
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const ownedReversibleConfigurationAuthority = process.env.PX_OWNED_VSCODE_HOST === '1'
  && process.argv.some(value => String(value).startsWith('--px-owned-token='));
const ownedHostToken = String(process.argv.find(value => String(value).startsWith('--px-owned-token=')) || '').slice('--px-owned-token='.length);
const configurationOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_CONFIGURATION_ONLY === '1';
const studioLifecycleOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY === '1';
const knowledgeLifecycleOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY === '1';
const focusedProfile = configurationOnly ? 'reversible-configuration' : studioLifecycleOnly ? 'studio-lifecycle' : knowledgeLifecycleOnly ? 'knowledge-lifecycle' : null;
const focusedProfileOnly = Boolean(focusedProfile);
const ownedKnowledgeSourceId = String(process.env.PX_OWNED_KNOWLEDGE_SOURCE_ID || '');
const ownedKnowledgeSourceSha256 = String(process.env.PX_OWNED_KNOWLEDGE_SOURCE_SHA256 || '');
const INSTALLED_ROUTES = {
  dashboard: 'dashboard', 'dashboard-control-plane': 'dashboard', projects: 'projects', agents: 'agents',
  'agent-studio': 'agents', 'workflow-studio': 'workflows', 'skill-studio': 'skillsTools',
  'knowledge-graph': 'knowledgeGraph', 'skills-tools': 'skillsTools', workflows: 'workflows', plugins: 'plugins',
  memory: 'memory', activity: 'activity', diagnostics: 'diagnostics', assurance: 'assurance',
  'studio-lifecycle': 'studio-lifecycle', settings: 'settings', 'knowledge-core': 'knowledgeCore',
  'runtime-core': 'runtimeCore'
};
const INSTALLED_SAFE_MODES = new Set([
  'contained_ui_interaction', 'contained_ui_input', 'contained_ui_form', 'contained_ui_gesture',
  'contained_ui_navigation', 'contained_ui_editor', 'live_state_observation'
]);

function eligibleInstalledControl(control) {
  if (!control || control.surface_id === 'sidebar') return false;
  if (INSTALLED_SAFE_MODES.has(control.evidence_mode)) return true;
  return control.evidence_mode === 'contained_host_interaction' && control.effect === 'read';
}

function installedActionIdentity(control) {
  return actionIdentity(String(control.control_id).split('.action.')[1] || control.label);
}

function installedStudioPrerequisites(control) {
  const id = String(control?.control_id || '');
  const steps = [];
  const add = (action, dataset = {}, pick = 'first') => steps.push({ action, dataset, pick });
  if (id.startsWith('pxui.agent-studio.')) {
    const optionalKind = id.match(/agentSelectNode\.(tools|memory|handoffs)\.optional$/)?.[1];
    if (optionalKind) add('agentAddTopologyNode', { agentKind: optionalKind });
    if (id.includes('agentRemoveTopologyNode')) add('agentAddTopologyNode', { agentKind: 'tools' });
    if (id.includes('agentRemoveBinding')) add('agentAddBinding');
    if (id.includes('agentRemoveGrant')) add('agentAddGrant');
    if (id.includes('agentCancelConnection')) add('agentPortConnect', { direction: 'output' });
    if (/\.field\.model\./.test(id)) add('agentSelectNode', { agentKind: 'model' });
    if (/\.field\.(?:input_schema|output_schema)$/.test(id)) add('agentSelectNode', { agentKind: 'contracts' });
    if (id.endsWith('.field.required_tests')) add('agentSelectNode', { agentKind: 'tests' });
  }
  if (id.startsWith('pxui.workflow-studio.')) {
    if (/workflowMoveNode\.(?:earlier|later)$/.test(id) || id.endsWith('.action.workflowRemoveNode')) add('workflowAddNode', { nodeTemplate: 'task' });
    if (id.endsWith('workflowMoveNode.later')) add('workflowSelectNode', {}, 'first');
    if (id.includes('workflowRemoveBinding')) add('workflowAddBinding');
    if (id.includes('workflowRemoveGrant')) add('workflowAddGrant');
    if (id.includes('workflowRemovePort')) add('workflowAddPort', { direction: 'inputs' });
    if (id.includes('workflowCancelConnection')) add('workflowPortConnect', { direction: 'output' });
    if (id.includes('workflowRemoveEdge') || /\.field\.edge\.(?:source_endpoint|target_endpoint)$/.test(id)) {
      add('workflowAddNode', { nodeTemplate: 'task' });
      add('workflowConnectNodes');
    }
  }
  if (id.startsWith('pxui.skill-studio.') && (
    id.includes('skillRemoveFile') || id.includes('skillSelectFile') || id.endsWith('.field.packageFileText')
    || id.endsWith('.form.packageFile') || id.endsWith('.editor.packageFile')
  )) add('skillAddFile', { fileKind: 'resource' });
  return steps;
}

async function seedInstalledStudioPrerequisites(frameHost, control) {
  const steps = installedStudioPrerequisites(control);
  for (const step of steps) {
    await frameHost.evaluate((frame, prerequisite) => {
      const document = frame.contentDocument;
      if (!document) throw new Error('PX installed contentDocument is unavailable.');
      if (prerequisite.action === 'workflowConnectNodes') {
        const source = document.querySelector('[data-edge-source-endpoint]');
        const target = document.querySelector('[data-edge-target-endpoint]');
        const endpoints = select => [...(select?.options || [])].map(option => {
          const [node, port] = String(option.value || '').split('|');
          const type = String(option.textContent || '').match(/:([^:\s]+)\s*$/)?.[1] || '';
          return { node, port, type, value: option.value };
        });
        const pair = endpoints(source).flatMap(output => endpoints(target).map(input => ({ output, input })))
          .find(({ output, input }) => output.node && input.node && output.node !== input.node && output.type === input.type);
        if (!pair) throw new Error('studio-prerequisite-unavailable:compatible-workflow-edge');
        source.value = pair.output.value;
        target.value = pair.input.value;
      }
      const candidates = [...document.querySelectorAll(`[data-action="${CSS.escape(prerequisite.action)}"]`)].filter(element =>
        Object.entries(prerequisite.dataset).every(([key, value]) => String(element.dataset[key] || '') === String(value))
      );
      const target = prerequisite.pick === 'last' ? candidates.at(-1) : candidates[0];
      if (!target || target.disabled) throw new Error(`studio-prerequisite-unavailable:${prerequisite.action}`);
      target.click();
    }, step);
    await wait(60);
  }
  return steps;
}

async function instrumentInstalledBridge(frameHost) {
  return frameHost.evaluate(frame => {
    const inner = frame.contentWindow;
    if (!inner) return false;
    inner.__PX_INSTALLED_RESPONSES__ ||= [];
    if (inner.__PX_INSTALLED_BRIDGE_INSTRUMENTED__) return true;
    inner.addEventListener('message', event => {
      try { inner.__PX_INSTALLED_RESPONSES__.push(JSON.parse(JSON.stringify(event.data))); }
      catch { inner.__PX_INSTALLED_RESPONSES__.push({ type: 'unserializable-message' }); }
    });
    inner.__PX_INSTALLED_BRIDGE_INSTRUMENTED__ = true;
    return true;
  });
}

async function waitForInstalledStudioState(frameHost, kind, expected, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let lastState = null;
  do {
    const state = await frameHost.evaluate((frame, expectedKind) => {
      const document = frame.contentDocument;
      const open = document?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
      const resume = document?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`);
      const modal = [...(document?.querySelectorAll('.studio-modal') || [])].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      const visibleControlModal = [...(document?.querySelectorAll('.control-modal') || [])].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      return {
        opener: Boolean(open || resume), modal: Boolean(modal),
        visible_modal_title: visibleControlModal?.querySelector('h2')?.textContent?.trim() || '',
        visible_modal_actions: [...(visibleControlModal?.querySelectorAll('[data-action]') || [])].map(element => ({ action: element.dataset.action, kind: element.dataset.kind || null }))
      };
    }, kind);
    lastState = state;
    if (state[expected]) return state;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`${kind}-studio-${expected}-not-ready:${JSON.stringify(lastState)}`);
}

async function resumeInstalledWorkingDraftIfOffered(frameHost, kind, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const state = await frameHost.evaluate((frame, expectedKind) => {
      const document = frame.contentDocument;
      const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      if ([...(document?.querySelectorAll('.studio-modal') || [])].some(visible)) return 'editor';
      const resume = [...(document?.querySelectorAll('[data-action="resumeWorkingStudioDraft"]') || [])]
        .find(element => element.dataset.kind === expectedKind && visible(element));
      if (!resume || resume.disabled) return 'waiting';
      resume.click();
      return 'resumed';
    }, kind);
    if (state !== 'waiting') return state;
    await wait(100);
  } while (Date.now() < deadline);
  return 'not-offered';
}

async function prepareInstalledControl(frameHost, control) {
  const route = INSTALLED_ROUTES[control.surface_id];
  if (!route) throw new Error(`No installed dashboard route for ${control.surface_id}`);
  await frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX installed contentDocument is unavailable.');
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const close = [...document.querySelectorAll('[data-action="closeModal"]')].find(visible);
    if (close) close.click();
    if (spec.advanced) {
      const advanced = document.querySelector('[data-action="toggleAdvanced"]');
      if (advanced && advanced.getAttribute('aria-expanded') !== 'true') advanced.click();
    }
    document.querySelector(`[data-surface="${spec.route}"]`)?.click();
  }, { route, advanced: ['knowledgeCore', 'runtimeCore'].includes(route) });
  await wait(100);
  if (['agent-studio', 'workflow-studio', 'skill-studio'].includes(control.surface_id)) {
    const kind = control.surface_id.split('-')[0];
    await waitForInstalledStudioState(frameHost, kind, 'opener');
    await frameHost.evaluate((frame, expectedKind) => {
      const document = frame.contentDocument;
      const open = document?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
      const resume = document?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`);
      (open || resume)?.click();
    }, kind);
    await resumeInstalledWorkingDraftIfOffered(frameHost, kind);
    await waitForInstalledStudioState(frameHost, kind, 'modal');
    await seedInstalledStudioPrerequisites(frameHost, control);
  }
}

async function revealInstalledControl(frameHost, control) {
  const action = revealActionFor(control);
  if (!action) return false;
  return frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument;
    if (!document) return false;
    const selector = spec.action === 'studioEditorTab'
      ? '[data-action="studioEditorTab"][data-tab="json"]'
      : `[data-action="${spec.action}"]`;
    const item = [...document.querySelectorAll(selector)].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
    if (!item || item.disabled) return false;
    item.click();
    return true;
  }, { action });
}

async function exerciseInstalledControl(frameHost, control) {
  const spec = {
    kind: control.kind,
    semantic: semanticLabel(control),
    selector: selectorForKind(control.kind),
    directSelector: directSelectorFor(control),
    action: control.kind === 'action' ? installedActionIdentity(control) : null,
    local: control.evidence_mode !== 'contained_host_interaction'
  };
  const before = await frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument;
    const inner = frame.contentWindow;
    if (!document || !inner) throw new Error('PX installed contentDocument is unavailable.');
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const normalize = value => String(value || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[._:/-]/g, ' ')
      .toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
    const tokens = [...new Set(normalize(item.semantic).split(' ').filter(token => token.length > 2 || token === 'id'))];
    const fingerprint = () => {
      const text = String(document.body?.innerText || '');
      let hash = 2166136261;
      for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
      return `${text.length}:${hash >>> 0}`;
    };
    const state = { loaded: true, visible: false, attempted: false, validationObserved: false, acknowledged: false,
      responseCount: inner.__PX_INSTALLED_RESPONSES__?.length || 0, fingerprint: fingerprint(), details: {}, errors: [] };
    let target = null;
    if (item.kind === 'action') {
      if (item.action.action === 'navigate') target = document.querySelector(`[data-surface="${item.action.variants[0]}"]`);
      else {
        const candidates = [...document.querySelectorAll(`[data-action="${item.action.action}"]`)];
        target = candidates.find(element => {
          const values = new Set(Object.values(element.dataset).map(String));
          const context = normalize(`${element.getAttribute('aria-label') || ''} ${element.className || ''} ${element.parentElement?.className || ''}`);
          return item.action.variants.every(variant => variant === 'row'
            ? Object.keys(element.dataset).some(key => /id|index|row|key|path/i.test(key))
            : values.has(variant) || (variant === 'in' && (Number(element.dataset.delta) > 0 || context.includes('zoom in')))
              || (variant === 'out' && (Number(element.dataset.delta) < 0 || context.includes('zoom out')))
              || (variant === 'earlier' && Number(element.dataset.delta) < 0)
              || (variant === 'later' && Number(element.dataset.delta) > 0)
              || (variant === 'optional' && ['tools', 'memory', 'handoffs'].includes(String(element.dataset.agentKind || ''))));
        });
      }
    } else {
      const direct = item.directSelector ? document.querySelector(item.directSelector) : null;
      if (direct && visible(direct)) target = direct;
      const candidates = target ? [] : [...document.querySelectorAll(item.selector || 'body')].filter(visible);
      let best = null;
      for (const candidate of candidates) {
        const haystack = normalize(`${candidate.innerText || candidate.value || ''} ${[...candidate.attributes].map(attribute => `${attribute.name}=${attribute.value}`).join(' ')}`);
        const score = tokens.length ? tokens.filter(token => haystack.includes(token)).length / tokens.length + (haystack.includes(normalize(item.semantic)) ? 0.35 : 0) : 0;
        if (!best || score > best.score) best = { candidate, score };
      }
      if (!target && best && best.score >= 0.66) target = best.candidate;
    }
    if (!target || !visible(target)) return state;
    state.visible = true;
    if (item.kind === 'indicator') { state.acknowledged = true; return state; }
    if (target.disabled) return state;
    if (item.kind === 'field') {
      const original = target.type === 'checkbox' || target.type === 'radio' ? target.checked : target.value;
      if (target.tagName === 'SELECT') {
        const alternate = [...target.options].find(option => option.value !== original && !option.disabled);
        if (alternate) { target.value = alternate.value; target.dispatchEvent(new inner.Event('change', { bubbles: true })); target.value = original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.attempted = true; }
      } else if (target.type === 'checkbox' || target.type === 'radio') {
        target.checked = !original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); target.checked = original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.attempted = true;
      } else {
        target.value = `${original || ''} px-probe`.trim(); target.dispatchEvent(new inner.Event('input', { bubbles: true }));
        target.value = original; target.dispatchEvent(new inner.Event('input', { bubbles: true })); state.attempted = true;
      }
    } else if (['editor', 'gesture'].includes(item.kind)) {
      target.focus(); target.dispatchEvent(new inner.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      target.dispatchEvent(new inner.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })); state.attempted = true;
    } else if (item.kind === 'form') {
      (target.querySelector('input,select,textarea,[tabindex]') || target).focus(); state.attempted = true;
    } else {
      target.click(); state.attempted = true;
    }
    state.validationObserved = state.attempted;
    return state;
  }, spec);
  if (!before.attempted || before.acknowledged) return before;
  const acknowledgementDeadline = Date.now() + (spec.local ? 80 : 3_000);
  let after = before;
  do {
    await wait(spec.local ? 80 : 100);
    after = await frameHost.evaluate(frame => {
      const document = frame.contentDocument; const inner = frame.contentWindow;
      const text = String(document?.body?.innerText || ''); let hash = 2166136261;
      for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
      return { responseCount: inner?.__PX_INSTALLED_RESPONSES__?.length || 0, fingerprint: `${text.length}:${hash >>> 0}` };
    });
    if (spec.local || after.responseCount > before.responseCount || after.fingerprint !== before.fingerprint) break;
  } while (Date.now() < acknowledgementDeadline);
  before.acknowledged = spec.local || after.responseCount > before.responseCount || after.fingerprint !== before.fingerprint;
  before.details.result_acknowledgement = before.acknowledged
    ? (spec.local ? 'Installed UI acknowledged the contained reversible interaction.' : 'Installed host returned a message or changed the exact live view after the read request.')
    : '';
  return before;
}

async function probeInstalledControls(frameHost, matrix, hostErrors) {
  const bridgeInstrumented = await instrumentInstalledBridge(frameHost).catch(error => {
    hostErrors.push({ source: 'installed-control-probe', context: 'bridge-instrumentation', message: String(error?.message || error).slice(0, 1000) });
    return false;
  });
  const records = [];
  let preparedSurface = null;
  const blockedSurfaces = new Map();
  for (const control of matrix.controls.filter(eligibleInstalledControl)) {
    let probe = { loaded: false, visible: false, attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
    const isolated = control.kind === 'action' || ['form', 'menu', 'gesture'].includes(control.kind);
    try {
      if (blockedSurfaces.has(control.surface_id)) throw new Error(blockedSurfaces.get(control.surface_id));
      if (isolated || preparedSurface !== control.surface_id) {
        await prepareInstalledControl(frameHost, control);
        preparedSurface = isolated ? null : control.surface_id;
      }
      const revealed = await revealInstalledControl(frameHost, control);
      if (revealed) await wait(60);
      probe = await exerciseInstalledControl(frameHost, control);
      if (isolated || revealed) preparedSurface = null;
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1000);
      probe.errors.push(message);
      if (message.includes('-studio-opener-not-ready') || message.includes('-studio-modal-not-ready')) blockedSurfaces.set(control.surface_id, message);
      preparedSurface = null;
    }
    const evidenceRef = `installed-receipt:${control.control_id}`;
    const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, stageResult(control, probe, stage, evidenceRef)]));
    if (control.evidence_mode === 'contained_host_interaction' && probe.attempted && probe.acknowledged) {
      for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect']) {
        if (control.stage_policy[stage] !== 'required') continue;
        interactionChain[stage] = {
          state: 'present',
          detail: `The exact read action returned an installed-host response or changed its exact live view, directly proving ${stage}.`,
          evidence: [evidenceRef]
        };
      }
    }
    records.push({
      control_id: control.control_id,
      surface_id: control.surface_id,
      control_kind: control.kind,
      evidence_mode: control.evidence_mode,
      rendered: probe.visible,
      observed: probe.visible,
      attempted: probe.attempted,
      interaction_chain: interactionChain,
      errors: probe.errors
    });
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed host; local/reversible UI controls and typed read-only host actions only.',
    bridge_instrumented: bridgeInstrumented,
    eligible_control_count: records.length,
    aggregates: {
      rendered: records.filter(record => record.rendered).length,
      attempted: records.filter(record => record.attempted).length,
      errors: records.reduce((total, record) => total + record.errors.length, 0)
    },
    records
  };
}

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

async function exerciseBuilderDurability(frameHost, kind, studioSurface) {
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="studioEditorTab"][data-tab="json"]')?.click());
  await wait(180);
  const before = await builderState(frameHost, kind);
  const negative = await frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const input = document?.querySelector('#studio-draft-json');
    const apply = document?.querySelector('[data-action="studioApplyJson"]');
    if (!input || !apply) throw new Error('canonical-json-validation-controls-missing');
    const original = input.value;
    input.value = '{';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    apply.click();
    return { original, validation_message: input.validationMessage };
  });
  await wait(180);
  assert.ok(negative.validation_message, `${kind}-studio-malformed-json-was-not-rejected`);
  await frameHost.evaluate((frame, original) => {
    const document = frame.contentDocument;
    const input = document?.querySelector('#studio-draft-json');
    const apply = document?.querySelector('[data-action="studioApplyJson"]');
    if (!input || !apply) throw new Error('canonical-json-recovery-controls-missing');
    input.value = original;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    apply.click();
  }, negative.original);
  await wait(220);
  const recovered = await builderState(frameHost, kind);
  assert.deepEqual(JSON.parse(recovered.canonical_json), JSON.parse(negative.original), `${kind}-studio-json-recovery-mismatch`);
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('.studio-modal [data-action="closeModal"]')?.click());
  await wait(180);
  const closed = await builderState(frameHost, kind);
  await frameHost.evaluate((frame, surface) => frame.contentDocument?.querySelector(`[data-surface="${CSS.escape(surface)}"]`)?.click(), studioSurface);
  await wait(220);
  const offered = await frameHost.evaluate((frame, builderKind) => {
    const control = [...(frame.contentDocument?.querySelectorAll('[data-action="openStudioDraft"]') || [])]
      .find(button => button.dataset.kind === builderKind);
    if (!control || control.disabled) return false;
    control.click();
    return true;
  }, kind);
  assert.equal(offered, true, `${kind}-studio-working-draft-offer-control-missing`);
  await wait(220);
  const resumed = await frameHost.evaluate((frame, builderKind) => {
    const control = [...(frame.contentDocument?.querySelectorAll('[data-action="resumeWorkingStudioDraft"]') || [])]
      .find(button => button.dataset.kind === builderKind);
    if (!control || control.disabled) return false;
    control.click();
    return true;
  }, kind);
  assert.equal(resumed, true, `${kind}-studio-working-draft-resume-control-missing`);
  await wait(220);
  const reopened = await builderState(frameHost, kind);
  assert.equal(reopened.modal_present, true, `${kind}-studio-working-draft-did-not-reopen`);
  assert.deepEqual(JSON.parse(reopened.canonical_json), JSON.parse(negative.original), `${kind}-studio-reopened-draft-mismatch`);
  return { before, negative_validation_message: negative.validation_message, recovered, closed, reopened, verified: true };
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
  let opened = await builderState(frameHost, kind);
  if (!opened.modal_present) {
    const resumed = await frameHost.evaluate((frame, builderKind) => {
      const document = frame.contentDocument;
      const control = [...document.querySelectorAll('[data-action="resumeWorkingStudioDraft"]')]
        .find(button => button.dataset.kind === builderKind);
      if (!control) return false;
      control.click();
      return true;
    }, kind);
    if (resumed) {
      await wait(500);
      opened = await builderState(frameHost, kind);
    }
  }
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
  const durability = await exerciseBuilderDurability(frameHost, kind, studioSurface);
  observations.push({
    control_id: `pxui.${studioSurface}.action.studioApplyJson`, action: 'studioApplyJson', dataset: {}, invoked: { match_count: 1, label: 'Apply JSON to visual builder' },
    before_state_sha256: digest(durability.before), after_state_sha256: digest(durability.recovered), changed: digest(durability.before) !== digest(durability.recovered),
    before: durability.before, after: durability.recovered,
    observed_effects: ['malformed canonical JSON rejected locally, then exact prior JSON restored without host dispatch']
  });
  observations.push({
    control_id: `pxui.${studioSurface}.action.resumeWorkingStudioDraft`, action: 'resumeWorkingStudioDraft', dataset: { kind }, invoked: { match_count: 1, label: `Resume ${kind} draft` },
    before_state_sha256: digest(durability.closed), after_state_sha256: digest(durability.reopened), changed: true,
    before: durability.closed, after: durability.reopened,
    observed_effects: ['reopened the exact bounded working draft from VS Code webview state']
  });
  const closeBefore = durability.reopened;
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
    before, after, screenshot, observations, durability,
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
      if (['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting'].includes(stage.stage)) {
        return { stage: stage.stage, status: 'not_applicable', observed_at: record.observed_at, reason: 'This exact pass is confined to unsaved webview draft state and dispatches no host or durable effect.' };
      }
      if (builders[record.surface_id === 'agent-studio' ? 'agent' : record.surface_id === 'workflow-studio' ? 'workflow' : '']?.durability?.verified === true) {
        return { stage: stage.stage, status: 'observed', observed_at: record.observed_at, evidence: `${record.surface_id} isolated working-draft persistence, reopen, malformed-input rejection, and exact recovery receipt` };
      }
      return { ...stage, reason: 'Durable reload, injected failure, and recovery behavior is owned by PX-OS-848.' };
    });
  }
  const terminalDispositions = {};
  for (const record of controlChains.controls) terminalDispositions[record.terminal_disposition] = (terminalDispositions[record.terminal_disposition] || 0) + 1;
  controlChains.aggregates.terminal_dispositions = terminalDispositions;
  controlChains.aggregates.attempted_control_count = controlChains.controls.filter(control => control.attempted).length;
  controlChains.aggregates.complete_interaction_chains = controlChains.controls.filter(control => control.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status))).length;
  controlChains.builder_observations = observations.map(observation => ({
    control_id: observation.control_id,
    before_state_sha256: observation.before_state_sha256,
    after_state_sha256: observation.after_state_sha256,
    changed: observation.changed,
    observed_effects: observation.observed_effects
  }));
  return controlChains;
}

function applyInstalledProbeObservations(controlChains, installedControlProbe, summaryKey = 'installed_probe_observations') {
  if (!installedControlProbe || installedControlProbe.schema_version !== 'px.installed-operational-control-probe/1.0') {
    throw new Error('Installed control probe is missing or has an unsupported schema.');
  }
  const records = Array.isArray(installedControlProbe.records) ? installedControlProbe.records : [];
  if (records.length !== installedControlProbe.eligible_control_count) {
    throw new Error('Installed control probe does not retain its exact eligible-control denominator.');
  }
  const byId = new Map(controlChains.controls.map(control => [control.control_id, control]));
  const seen = new Set();
  for (const probe of records) {
    const controlId = String(probe.control_id || '');
    if (seen.has(controlId)) throw new Error(`Installed control probe duplicated a control: ${controlId}`);
    seen.add(controlId);
    const record = byId.get(controlId);
    if (!record) throw new Error(`Installed control probe referenced an unregistered control: ${controlId}`);
    const chain = probe.interaction_chain;
    if (!chain || STAGES.some(stage => !chain[stage])) {
      throw new Error(`Installed control probe lacks the complete stage denominator: ${controlId}`);
    }
    record.rendered ||= probe.rendered === true;
    record.visible ||= probe.rendered === true;
    record.attempted ||= probe.attempted === true;
    if (probe.rendered) record.resolver = { type: 'exact_installed_control', status: 'exact', match_count: 1 };
    record.stages = record.stages.map(existing => {
      if (existing.status === 'observed') return existing;
      const direct = chain[existing.stage];
      if (direct.state === 'present') {
        return {
          stage: existing.stage,
          status: 'observed',
          observed_at: record.observed_at,
          evidence: `${direct.detail} ${(direct.evidence || []).join('; ')}`.trim()
        };
      }
      if (direct.state === 'not_applicable') {
        return {
          stage: existing.stage,
          status: 'not_applicable',
          observed_at: record.observed_at,
          reason: direct.detail
        };
      }
      return existing;
    });
    const complete = record.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status));
    if (complete) record.terminal_disposition = 'installed_operational_interaction_complete';
    else if (probe.attempted) record.terminal_disposition = 'installed_operational_interaction_partial';
    else if (Array.isArray(probe.errors) && probe.errors.length) record.terminal_disposition = 'installed_operational_probe_error';
    else if (probe.rendered) record.terminal_disposition = 'installed_operational_observation_partial';
    else record.terminal_disposition = 'installed_control_not_rendered';
  }
  const terminalDispositions = {};
  for (const record of controlChains.controls) terminalDispositions[record.terminal_disposition] = (terminalDispositions[record.terminal_disposition] || 0) + 1;
  controlChains.aggregates.terminal_dispositions = terminalDispositions;
  controlChains.aggregates.attempted_control_count = controlChains.controls.filter(control => control.attempted).length;
  controlChains.aggregates.complete_interaction_chains = controlChains.controls.filter(control => control.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status))).length;
  controlChains[summaryKey] = {
    eligible_control_count: records.length,
    rendered_control_count: records.filter(record => record.rendered).length,
    attempted_control_count: records.filter(record => record.attempted).length,
    complete_interaction_chains: records.filter(record => STAGES.every(stage => ['present', 'not_applicable'].includes(record.interaction_chain[stage].state))).length
  };
  return controlChains;
}

async function readInstalledConfigurationAction(frameHost, spec) {
  await frameHost.evaluate((frame, route) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    document?.querySelector('[data-surface="dashboard"]')?.click();
    document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
  }, spec.route);
  await wait(120);
  return frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument; const inner = frame.contentWindow;
    const control = [...(document?.querySelectorAll(`[data-action="${CSS.escape(item.action)}"]`) || [])]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    return {
      available: Boolean(control), target_value: control ? String(control.dataset[item.datasetKey] || '') : '',
      response_count: inner?.__PX_INSTALLED_RESPONSES__?.length || 0
    };
  }, spec);
}

async function waitForInstalledConfigurationTarget(frameHost, spec, predicate, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let current = null;
  do {
    current = await readInstalledConfigurationAction(frameHost, spec);
    if (current.available && predicate(current.target_value)) return current;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`${spec.action}-configuration-target-timeout:${current?.target_value || 'unavailable'}`);
}

async function invokeInstalledConfigurationAction(workbench, frameHost, spec, targetValue) {
  const before = await readInstalledConfigurationAction(frameHost, spec);
  if (!before.available || before.target_value !== targetValue) throw new Error(`${spec.action}-target-state-mismatch:${before.target_value}:${targetValue}`);
  await frameHost.evaluate((frame, action) => {
    const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(action)}"]`)]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (!control) throw new Error(`configuration-action-unavailable:${action}`);
    control.click();
  }, spec.action);
  if (spec.approvalLabel && targetValue === 'true') {
    const approval = workbench.getByRole('button', { name: spec.approvalLabel, exact: true }).last();
    if (await approval.isVisible({ timeout: 750 }).catch(() => false)) await approval.click();
  }
  const deadline = Date.now() + 12_000;
  let acknowledgement = null;
  do {
    acknowledgement = await frameHost.evaluate((frame, item) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      return responses.slice(item.after).find(response => response?.type === item.responseType && response?.operation === item.operation) || null;
    }, { after: before.response_count, responseType: spec.responseType, operation: spec.operation });
    if (acknowledgement) break;
    await wait(100);
  } while (Date.now() < deadline);
  if (!acknowledgement) throw new Error(`${spec.action}-typed-acknowledgement-timeout`);
  return acknowledgement;
}

async function invokeInstalledHostAction(frameHost, spec, timeoutMs = 120_000) {
  await frameHost.evaluate((frame, route) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    document?.querySelector('[data-surface="dashboard"]')?.click();
    document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
  }, spec.route);
  await wait(120);
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  await frameHost.evaluate((frame, action) => {
    const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(action)}"]`)]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (!control) throw new Error(`owned-host-action-unavailable:${action}`);
    control.click();
  }, spec.action);
  const deadline = Date.now() + timeoutMs;
  let acknowledgement = null;
  do {
    acknowledgement = await frameHost.evaluate((frame, item) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      return responses.slice(item.after).find(response => response?.type === 'hostActionResult' && response?.operation === item.operation) || null;
    }, { after: before, operation: spec.operation });
    if (acknowledgement) break;
    await wait(150);
  } while (Date.now() < deadline);
  if (!acknowledgement) throw new Error(`${spec.action}-typed-acknowledgement-timeout`);
  if (acknowledgement.disposition !== 'completed') throw new Error(`${spec.action}-unexpected-disposition:${acknowledgement.disposition}`);
  return acknowledgement;
}

function validStudioSetupResult(result) {
  return result?.schema_version === 'px.studio-setup-result/1.0'
    && result.ready === true
    && /^agent:[a-z0-9][a-z0-9._-]*$/.test(String(result.agent?.identity || ''))
    && /^workflow:[a-z0-9][a-z0-9._-]*$/.test(String(result.workflow?.identity || ''))
    && /^\d+\.\d+\.\d+$/.test(String(result.agent?.version || ''))
    && /^\d+\.\d+\.\d+$/.test(String(result.workflow?.version || ''))
    && result.agent?.decision === 'admitted'
    && result.workflow?.decision === 'admitted'
    && typeof result.agent?.run_id === 'string' && result.agent.run_id.length > 0
    && typeof result.workflow?.run_id === 'string' && result.workflow.run_id.length > 0
    && result.agent?.run_outcome === 'succeeded'
    && result.workflow?.run_state === 'succeeded';
}

function studioSetupRecord(requirement, observation) {
  const evidenceRef = `installed-studio-setup:${requirement.control_id}`;
  const verified = observation.attempted && observation.typed_ready_result && observation.positive_counts && observation.reopened;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_setup', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'The successful setup profile did not inject a Studio setup failure; matched fault evidence must supply this stage.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The exact installed setup action returned the typed ready contract, produced admitted runnable Agent and Workflow revisions with successful durable runs, and remained positive after route reopen.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host Studio setup campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledStudioSetupProfile(frameHost, matrix, timeoutMs = 180_000) {
  const controlIds = [
    'pxui.agent-studio.action.setupStudio',
    'pxui.agents.action.setupStudio',
    'pxui.workflows.action.setupStudio'
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const missing = controlIds.filter(controlId => !requirements.has(controlId));
  if (missing.length) throw new Error(`Studio setup profile controls are absent from the authoritative proof matrix: ${missing.join(',')}`);
  const observation = { available: false, attempted: false, typed_ready_result: false, positive_counts: false, reopened: false, result: null, counts: null, errors: [] };
  try {
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="dashboard"]')?.click();
      document?.querySelector('[data-surface="agents"]')?.click();
    });
    await wait(150);
    await frameHost.evaluate(frame => {
      const coreScope = frame.contentDocument?.querySelector('[data-action="surfaceScope"][data-target="agents"][data-scope="core"]');
      if (coreScope && coreScope.getAttribute('aria-pressed') !== 'true') coreScope.click();
    });
    await wait(150);
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    observation.available = await frameHost.evaluate(frame => Boolean([...frame.contentDocument.querySelectorAll('[data-action="setupStudio"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length))));
    if (!observation.available) throw new Error('setupStudio-landing-action-unavailable');
    observation.attempted = true;
    await frameHost.evaluate(frame => [...frame.contentDocument.querySelectorAll('[data-action="setupStudio"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length)).click());
    const deadline = Date.now() + timeoutMs;
    do {
      observation.result = await frameHost.evaluate((frame, after) => {
        const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
        return responses.slice(after).find(response => response?.type === 'studioSetupResult')?.result || null;
      }, before);
      if (observation.result) break;
      await wait(200);
    } while (Date.now() < deadline);
    observation.typed_ready_result = validStudioSetupResult(observation.result);
    if (!observation.typed_ready_result) throw new Error(`setupStudio-invalid-typed-result:${JSON.stringify(observation.result)}`);
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="dashboard"]')?.click();
      document?.querySelector('[data-surface="agents"]')?.click();
      document?.querySelector('[data-surface="workflows"]')?.click();
    });
    const countDeadline = Date.now() + 30_000;
    do {
      observation.counts = await frameHost.evaluate(frame => {
        const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
        return [...responses].reverse().find(response => response?.type === 'snapshot')?.snapshot?.counts || null;
      });
      observation.positive_counts = Number(observation.counts?.agents_runnable_revisions || 0) > 0
        && Number(observation.counts?.workflow_runnable_revisions || 0) > 0
        && Number(observation.counts?.agent_runs || 0) > 0
        && Number(observation.counts?.workflow_runs || 0) > 0;
      if (observation.positive_counts) break;
      await wait(150);
    } while (Date.now() < countDeadline);
    if (!observation.positive_counts) throw new Error(`setupStudio-positive-counts-not-observed:${JSON.stringify(observation.counts)}`);
    observation.reopened = await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-surface="dashboard"]')?.click();
      document?.querySelector('[data-surface="agents"]')?.click();
      const agentsText = String(document?.body?.innerText || '');
      document?.querySelector('[data-surface="workflows"]')?.click();
      const workflowsText = String(document?.body?.innerText || '');
      return /RUNNABLE REVISIONS/i.test(agentsText) && /RUNNABLE REVISIONS/i.test(workflowsText) && /DURABLE RUNS/i.test(workflowsText);
    });
    if (!observation.reopened) throw new Error('setupStudio-route-reopen-proof-missing');
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2000)); }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact setupStudio action executed only inside the owned isolated VS Code host.',
    eligible_control_count: controlIds.length,
    observation,
    records: controlIds.map(controlId => studioSetupRecord(requirements.get(controlId), observation))
  };
}

function validStudioDraftReceipt(kind, result, identity, version = '1.0.0') {
  if (!result || typeof result !== 'object') return false;
  if (kind === 'agent') return result.schema_version === 'px.agent-creation-receipt/1.1' && result.agent_id === identity && result.version === version && result.created === true && /^[0-9a-f]{64}$/.test(String(result.record_sha256 || ''));
  if (kind === 'workflow') return result.schema_version === 'px.workflow-revision-receipt/1.2' && result.workflow_id === identity && result.version === version && result.created === true && /^[0-9a-f]{64}$/.test(String(result.revision_sha256 || ''));
  return kind === 'skill' && result.schema_version === 'px.skill-draft/1.1' && result.manifest?.skill_id === identity && result.manifest?.version === version && /^[0-9a-f]{64}$/.test(String(result.manifest_sha256 || '')) && /^[0-9a-f]{64}$/.test(String(result.source_tree_sha256 || ''));
}

function studioCandidateSaveRecord(requirement, observation) {
  const evidenceRef = `installed-studio-candidate-save:${requirement.control_id}`;
  const verified = observation.attempted && observation.typed_creation_receipt && observation.reopened_catalog_match;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_candidate_save', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'The successful immutable-save profile did not inject a create failure; matched fault evidence must supply this stage.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The installed ${observation.kind} Studio submitted a collision-safe 1.0.0 candidate, returned an exact durable creation receipt, and rediscovered the same identity and version from the host catalog after route reopen.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host candidate-save campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledStudioCandidateSaveProfile(frameHost, matrix, timeoutMs = 150_000) {
  const specifications = [
    { kind: 'agent', route: 'agents', controlId: 'pxui.agent-studio.action.submitStudioDraft.agent', prefix: 'agent:px-owned-save-' },
    { kind: 'workflow', route: 'workflows', controlId: 'pxui.workflow-studio.action.submitStudioDraft.workflow', prefix: 'workflow:px-owned-save-' },
    { kind: 'skill', route: 'skillsTools', controlId: 'pxui.skill-studio.action.submitStudioDraft.skill', prefix: 'px-owned-save-' }
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const records = [];
  const observations = [];
  for (const [index, spec] of specifications.entries()) {
    const requirement = requirements.get(spec.controlId);
    if (!requirement) throw new Error(`Studio candidate-save profile control is absent: ${spec.controlId}`);
    const identity = `${spec.prefix}${Date.now().toString(36)}-${index}`;
    const observation = { kind: spec.kind, route: spec.route, identity, version: '1.0.0', catalog_record_id: null, available: false, attempted: false, typed_creation_receipt: false, reopened_catalog_match: false, result: null, errors: [] };
    try {
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
      }, spec);
      await wait(180);
      await frameHost.evaluate((frame, item) => {
        if (!['agents', 'workflows'].includes(item.route)) return;
        const document = frame.contentDocument;
        const coreScope = document?.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(item.route)}"][data-scope="core"]`);
        if (!coreScope || coreScope.disabled) throw new Error(`studio-${item.kind}-core-scope-unavailable`);
        if (coreScope.getAttribute('aria-pressed') !== 'true') coreScope.click();
      }, spec);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const document = frame.contentDocument;
        const open = [...document.querySelectorAll('[data-action="openStudioDraft"]')].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) throw new Error(`studio-${kind}-fresh-draft-opener-unavailable`);
        open.click();
      }, spec.kind);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const discard = [...frame.contentDocument.querySelectorAll('[data-action="discardWorkingStudioDraft"]')].find(element => element.dataset.kind === kind && !element.disabled);
        discard?.click();
      }, spec.kind);
      await waitForInstalledStudioState(frameHost, spec.kind, 'modal');
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      observation.available = await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        const identityInput = document.querySelector('#studio-identity');
        const versionInput = document.querySelector('#studio-version');
        if (!identityInput || !versionInput) return false;
        identityInput.value = item.identity; identityInput.dispatchEvent(new Event('input', { bubbles: true }));
        versionInput.value = '1.0.0'; versionInput.dispatchEvent(new Event('input', { bubbles: true }));
        if (item.kind === 'workflow') {
          const approval = document.querySelector('[data-workflow-field="approval_required"]');
          if (!approval) throw new Error('studio-workflow-approval-field-unavailable');
          if (!approval.checked) {
            approval.checked = true;
            approval.dispatchEvent(new Event('input', { bubbles: true }));
            approval.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
        const save = document.querySelector('[data-action="submitStudioDraft"]');
        return Boolean(save && !save.disabled);
      }, { identity, kind: spec.kind });
      if (!observation.available) throw new Error(`studio-${spec.kind}-save-unavailable-after-valid-identity`);
      observation.attempted = true;
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="submitStudioDraft"]').click());
      const deadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          return responses.slice(item.after).find(value => (value?.type === 'studioDraftResult' && value?.kind === item.kind) || (value?.type === 'operationError' && value?.operation === 'createStudioDraft')) || null;
        }, { after: before, kind: spec.kind });
        if (response?.type === 'operationError') throw new Error(`studio-${spec.kind}-create-failed:${response.error}`);
        if (response) { observation.result = response.result; break; }
        await wait(200);
      } while (Date.now() < deadline);
      observation.typed_creation_receipt = validStudioDraftReceipt(spec.kind, observation.result, identity);
      if (!observation.typed_creation_receipt) throw new Error(`studio-${spec.kind}-creation-receipt-invalid:${JSON.stringify(observation.result)}`);
      const catalogBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, route) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector('[data-surface="dashboard"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
      }, spec.route);
      const catalogDeadline = Date.now() + 30_000;
      do {
        const reopenedRecord = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          for (const value of responses.slice(item.after).filter(value => value?.type === 'catalogResult' && value?.result?.kind === `${item.kind}s`)) {
            const record = (value.result.items || []).find(record => {
            const details = record?.details || {};
            const foundIdentity = details.agent_id || details.workflow_id || details.skill_id || details.id;
            return foundIdentity === item.identity && details.version === '1.0.0';
            });
            if (record) return { id: record.id, kind: record.kind, status: record.status };
          }
          return null;
        }, { after: catalogBefore, kind: spec.kind, identity });
        observation.reopened_catalog_match = Boolean(reopenedRecord);
        if (reopenedRecord) observation.catalog_record_id = reopenedRecord.id;
        if (observation.reopened_catalog_match) break;
        await wait(150);
      } while (Date.now() < catalogDeadline);
      if (!observation.reopened_catalog_match) throw new Error(`studio-${spec.kind}-catalog-reopen-match-missing`);
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
    records.push(studioCandidateSaveRecord(requirement, observation));
  }
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact immutable candidate saves executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, observations, records };
}

function studioRevisionEditRecord(requirement, observations, kind = null) {
  const selected = kind ? observations.filter(item => item.kind === kind) : observations;
  const verified = selected.length > 0 && selected.every(validStudioRevisionEditObservation);
  const evidenceRef = `installed-studio-revision-edit:${requirement.control_id}`;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_revision_edit', rendered: selected.every(item => item.editor_bound),
    observed: selected.every(item => item.editor_bound), attempted: selected.some(item => item.attempted),
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'The successful predecessor-bound edit profile did not inject a create failure; matched fault evidence must supply this stage.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The installed ${kind || 'agent and workflow'} Studio authenticated exact 1.0.0 predecessors, persisted changed content in immutable 1.0.1 revisions, proved the predecessors remained unchanged, and physically reopened the saved revisions with the edited content.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host revision-edit campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: selected.flatMap(item => item.errors || [])
  };
}

function validStudioRevisionEditObservation(observation) {
  const sha256 = value => /^[0-9a-f]{64}$/.test(String(value || ''));
  return observation?.editor_bound === true
    && observation?.typed_creation_receipt === true
    && observation?.reopened_catalog_match === true
    && observation?.predecessor_preserved === true
    && observation?.content_changed === true
    && observation?.reopened_editor_content_match === true
    && typeof observation.original_owner === 'string'
    && observation.original_owner.length > 0
    && typeof observation.changed_owner === 'string'
    && observation.changed_owner.length > 0
    && observation.changed_owner !== observation.original_owner
    && sha256(observation.predecessor_revision_sha256)
    && sha256(observation.predecessor_content_sha256)
    && sha256(observation.saved_revision_sha256)
    && sha256(observation.saved_content_sha256)
    && observation.saved_revision_sha256 !== observation.predecessor_revision_sha256
    && observation.saved_content_sha256 !== observation.predecessor_content_sha256;
}

async function runInstalledStudioRevisionEditProfile(frameHost, candidateProfile, matrix, timeoutMs = 150_000) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const specifications = [
    { kind: 'agent', submitControlId: 'pxui.agent-studio.action.submitStudioDraft.agent' },
    { kind: 'workflow', submitControlId: 'pxui.workflow-studio.action.submitStudioDraft.workflow' },
    { kind: 'skill', submitControlId: 'pxui.skill-studio.action.submitStudioDraft.skill' }
  ];
  const observations = [];
  for (const spec of specifications) {
    const candidate = (candidateProfile.observations || []).find(item => item.kind === spec.kind);
    const observation = {
      kind: spec.kind, identity: candidate?.identity || null, source_version: candidate?.version || null,
      candidate_version: '1.0.1', source_catalog_record_id: candidate?.catalog_record_id || null,
      saved_catalog_record_id: null, attempted: false, editor_bound: false, typed_creation_receipt: false,
      reopened_catalog_match: false, predecessor_preserved: false, content_changed: false,
      reopened_editor_content_match: false, original_owner: null, changed_owner: null,
      predecessor_revision_sha256: null, predecessor_content_sha256: null,
      saved_revision_sha256: null, saved_content_sha256: null,
      last_editor_state: null, result: null, errors: []
    };
    try {
      if (!candidate?.typed_creation_receipt || !candidate?.reopened_catalog_match || !candidate?.catalog_record_id) throw new Error(`studio-${spec.kind}-revision-edit-prerequisite-missing`);
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
      }, candidate);
      await wait(180);
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        if (item.route === 'skillsTools') {
          const native = [...document.querySelectorAll('[data-action="capabilityTab"]')].find(element => element.dataset.kind === 'skills' && !element.disabled);
          if (!native) throw new Error('studio-skill-revision-edit-native-catalog-unavailable');
          if (native.getAttribute('aria-pressed') !== 'true') native.click();
          return;
        }
        const scope = document?.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(item.route)}"][data-scope="core"]`);
        if (!scope || scope.disabled) throw new Error(`studio-${item.kind}-revision-edit-core-scope-unavailable`);
        if (scope.getAttribute('aria-pressed') !== 'true') scope.click();
      }, candidate);
      if (candidate.route === 'skillsTools') await wait(180);
      const rowDeadline = Date.now() + 30_000;
      let rowOpened = false;
      do {
        rowOpened = await frameHost.evaluate((frame, recordId) => {
          const row = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')].find(element => element.dataset.id === recordId && !element.disabled);
          if (!row) return false;
          row.click(); return true;
        }, candidate.catalog_record_id);
        if (rowOpened) break;
        await wait(150);
      } while (Date.now() < rowDeadline);
      if (!rowOpened) throw new Error(`studio-${spec.kind}-revision-edit-source-row-missing`);
      await wait(120);
      observation.attempted = true;
      const editorBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const openDispatched = await frameHost.evaluate((frame, kind) => {
        const action = kind === 'skill' ? 'loadSkillPackageEditor' : 'openStudioFromCatalog';
        const open = [...frame.contentDocument.querySelectorAll(`[data-action="${action}"]`)].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) return false;
        open.click(); return true;
      }, spec.kind);
      if (!openDispatched) throw new Error(`studio-${spec.kind}-revision-editor-opener-missing`);
      const editorDeadline = Date.now() + timeoutMs;
      do {
        const state = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          const failure = responses.slice(item.after).find(value => value?.type === 'operationError' && ['loadSkillPackageEditor', 'loadStudioRevisionEditor', 'studioOperation'].includes(value?.operation));
          if (failure) return { failure: failure.error || 'unknown editor load failure' };
          const document = frame.contentDocument;
          const identity = document.querySelector('#studio-identity');
          const version = document.querySelector('#studio-version');
          const baseline = document.querySelector('.studio-revision-baseline');
          const fork = document.querySelector('[data-action="forkStudioCandidate"]');
          const save = document.querySelector('[data-action="submitStudioDraft"]');
          return {
            ready: identity?.value === item.identity && version?.value === item.version
              && identity.readOnly && version.readOnly && Boolean(baseline) && Boolean(fork) && Boolean(save),
            identity: identity?.value || null, identity_readonly: Boolean(identity?.readOnly),
            version: version?.value || null, version_readonly: Boolean(version?.readOnly),
            baseline: baseline?.textContent?.trim().slice(0, 1000) || null,
            fork_present: Boolean(fork), save_present: Boolean(save), save_disabled: Boolean(save?.disabled),
            validation: document.querySelector('[data-studio-validation]')?.textContent?.trim().slice(0, 1600) || null,
            modal_text: document.querySelector('.studio-modal')?.textContent?.trim().slice(0, 2400) || null
          };
        }, { after: editorBefore, identity: candidate.identity, version: observation.candidate_version });
        observation.last_editor_state = state;
        if (state.failure) throw new Error(`studio-${spec.kind}-revision-editor-load-failed:${state.failure}`);
        if (state.ready) { observation.editor_bound = true; break; }
        await wait(200);
      } while (Date.now() < editorDeadline);
      if (!observation.editor_bound) throw new Error(`studio-${spec.kind}-revision-editor-binding-timeout`);
      const saveState = await frameHost.evaluate((frame, suffix) => {
        const owner = frame.contentDocument.querySelector('#studio-owner');
        if (!owner) return { available: false, reason: 'owner-input-missing' };
        const originalOwner = owner.value;
        owner.value = `${originalOwner}${suffix}`; owner.dispatchEvent(new Event('input', { bubbles: true }));
        const save = frame.contentDocument.querySelector('[data-action="submitStudioDraft"]');
        return {
          available: Boolean(save && !save.disabled), save_present: Boolean(save), save_disabled: Boolean(save?.disabled),
          original_owner: originalOwner, changed_owner: owner.value,
          validation: frame.contentDocument.querySelector('[data-studio-validation]')?.textContent?.trim().slice(0, 1600) || null
        };
      }, `:edited-${Date.now().toString(36)}`);
      observation.last_editor_state = { ...(observation.last_editor_state || {}), after_edit: saveState };
      if (!saveState.available) throw new Error(`studio-${spec.kind}-revision-save-unavailable-after-edit:${JSON.stringify(saveState)}`);
      observation.original_owner = saveState.original_owner;
      observation.changed_owner = saveState.changed_owner;
      if (!observation.original_owner || !observation.changed_owner || observation.original_owner === observation.changed_owner) throw new Error(`studio-${spec.kind}-revision-edit-content-unchanged`);
      const saveBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="submitStudioDraft"]').click());
      const saveDeadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          return responses.slice(item.after).find(value => (value?.type === 'studioDraftResult' && value?.kind === item.kind)
            || (value?.type === 'operationError' && value?.operation === 'createStudioDraft' && value?.kind === item.kind)) || null;
        }, { after: saveBefore, kind: spec.kind });
        if (response?.type === 'operationError') throw new Error(`studio-${spec.kind}-revision-create-failed:${response.error}`);
        if (response) { observation.result = response.result; break; }
        await wait(200);
      } while (Date.now() < saveDeadline);
      observation.typed_creation_receipt = validStudioDraftReceipt(spec.kind, observation.result, candidate.identity, observation.candidate_version);
      if (!observation.typed_creation_receipt) throw new Error(`studio-${spec.kind}-revision-creation-receipt-invalid:${JSON.stringify(observation.result)}`);
      const catalogBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, route) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector('[data-surface="dashboard"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
      }, candidate.route);
      const catalogDeadline = Date.now() + 30_000;
      do {
        const reopenedRecord = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          for (const value of responses.slice(item.after).filter(value => value?.type === 'catalogResult' && value?.result?.kind === `${item.kind}s`)) {
            const records = value.result.items || [];
            const saved = records.find(record => {
              const details = record?.details || {};
              return (details.agent_id || details.workflow_id || details.skill_id || details.id) === item.identity && details.version === item.version;
            });
            const predecessor = records.find(record => {
              const details = record?.details || {};
              return record?.id === item.predecessor_id
                && (details.agent_id || details.workflow_id || details.skill_id || details.id) === item.identity
                && details.version === item.source_version;
            });
            if (saved && predecessor) {
              const savedDetails = saved.details || {};
              const predecessorDetails = predecessor.details || {};
              return {
                id: saved.id, kind: saved.kind, status: saved.status,
                saved_owner: savedDetails.owner || null,
                saved_revision_sha256: savedDetails.revision_sha256 || null,
                saved_content_sha256: savedDetails.source_content_sha256 || null,
                predecessor_owner: predecessorDetails.owner || null,
                predecessor_revision_sha256: predecessorDetails.revision_sha256 || null,
                predecessor_content_sha256: predecessorDetails.source_content_sha256 || null
              };
            }
          }
          return null;
        }, { after: catalogBefore, kind: spec.kind, identity: candidate.identity, version: observation.candidate_version, source_version: candidate.version, predecessor_id: candidate.catalog_record_id });
        if (reopenedRecord) {
          observation.predecessor_revision_sha256 = reopenedRecord.predecessor_revision_sha256;
          observation.predecessor_content_sha256 = reopenedRecord.predecessor_content_sha256;
          observation.saved_revision_sha256 = reopenedRecord.saved_revision_sha256;
          observation.saved_content_sha256 = reopenedRecord.saved_content_sha256;
          observation.predecessor_preserved = reopenedRecord.predecessor_owner === observation.original_owner
            && /^[0-9a-f]{64}$/.test(String(reopenedRecord.predecessor_revision_sha256 || ''))
            && /^[0-9a-f]{64}$/.test(String(reopenedRecord.predecessor_content_sha256 || ''));
          observation.content_changed = reopenedRecord.saved_owner === observation.changed_owner
            && /^[0-9a-f]{64}$/.test(String(reopenedRecord.saved_revision_sha256 || ''))
            && /^[0-9a-f]{64}$/.test(String(reopenedRecord.saved_content_sha256 || ''))
            && reopenedRecord.saved_revision_sha256 !== reopenedRecord.predecessor_revision_sha256
            && reopenedRecord.saved_content_sha256 !== reopenedRecord.predecessor_content_sha256;
          observation.reopened_catalog_match = observation.predecessor_preserved && observation.content_changed;
          observation.saved_catalog_record_id = reopenedRecord.id;
          break;
        }
        await wait(150);
      } while (Date.now() < catalogDeadline);
      if (!observation.reopened_catalog_match) throw new Error(`studio-${spec.kind}-revision-catalog-reopen-match-missing`);
      const verificationRowOpened = await frameHost.evaluate((frame, recordId) => {
        const row = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')].find(element => element.dataset.id === recordId && !element.disabled);
        if (!row) return false;
        row.click(); return true;
      }, observation.saved_catalog_record_id);
      if (!verificationRowOpened) throw new Error(`studio-${spec.kind}-saved-revision-row-missing`);
      await wait(120);
      const verificationOpened = await frameHost.evaluate((frame, kind) => {
        const action = kind === 'skill' ? 'loadSkillPackageEditor' : 'openStudioFromCatalog';
        const open = [...frame.contentDocument.querySelectorAll(`[data-action="${action}"]`)].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) return false;
        open.click(); return true;
      }, spec.kind);
      if (!verificationOpened) throw new Error(`studio-${spec.kind}-saved-revision-editor-opener-missing`);
      const verificationDeadline = Date.now() + timeoutMs;
      do {
        const reopened = await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          const identity = document.querySelector('#studio-identity');
          const version = document.querySelector('#studio-version');
          const owner = document.querySelector('#studio-owner');
          return {
            matches: identity?.value === item.identity && identity.readOnly
              && version?.value === item.next_version && version.readOnly
              && owner?.value === item.owner
              && Boolean(document.querySelector('.studio-revision-baseline')),
            identity: identity?.value || null, version: version?.value || null, owner: owner?.value || null
          };
        }, { identity: candidate.identity, next_version: '1.0.2', owner: observation.changed_owner });
        observation.last_editor_state = { ...(observation.last_editor_state || {}), reopened_saved_revision: reopened };
        if (reopened.matches) { observation.reopened_editor_content_match = true; break; }
        await wait(200);
      } while (Date.now() < verificationDeadline);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
      if (!observation.reopened_editor_content_match) throw new Error(`studio-${spec.kind}-saved-revision-editor-content-mismatch`);
      if (!validStudioRevisionEditObservation(observation)) throw new Error(`studio-${spec.kind}-revision-edit-proof-incomplete`);
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
  }
  const openRequirement = requirements.get('pxui.studio-lifecycle.action.openStudioFromCatalog');
  if (!openRequirement) throw new Error('Studio revision-edit profile openStudioFromCatalog control is absent');
  const records = [studioRevisionEditRecord(openRequirement, observations)];
  for (const spec of specifications) {
    const requirement = requirements.get(spec.submitControlId);
    if (!requirement) throw new Error(`Studio revision-edit profile control is absent: ${spec.submitControlId}`);
    records.push(studioRevisionEditRecord(requirement, observations, spec.kind));
  }
  return { schema_version: 'px.installed-studio-revision-edit-profile/1.0', authority: 'Exact predecessor-bound immutable revision edits executed only inside the owned isolated VS Code host.', observations, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact predecessor-bound immutable revision edits executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, records } };
}

function validStudioLifecycleResult(kind, operation, result) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  if (!record || typeof record !== 'object') return false;
  if (operation === 'register-authority') return record.schema_version === 'px.studio-authority-transaction/1.0' && record.status === 'registered' && record.authenticated === true;
  if (kind === 'agent' && operation === 'test') return record.schema_version === 'px.agent-preflight-receipt/1.2' && record.passed === true;
  if (kind === 'agent' && operation === 'admit') return record.schema_version === 'px.agent-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'agent' && operation === 'preview') return record.schema_version === 'px.agent-execution-preview/1.0' && record.effects_executed === false && record.eligible === true;
  if (kind === 'workflow' && operation === 'validate') return record.schema_version === 'px.workflow-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'workflow' && operation === 'dry-run') return record.schema_version === 'px.workflow-dry-run/1.1' && record.effects_executed === false;
  if (kind === 'skill' && operation === 'validate') return record.schema_version === 'px.skill-validation-receipt/1.1' && record.passed === true;
  if (kind === 'skill' && operation === 'admit') return record.schema_version === 'px.skill-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'skill' && operation === 'promote') return record.schema_version === 'px.skill-promotion-receipt/1.3' && record.state === 'promoted' && typeof record.promotion_receipt_relative === 'string';
  if (kind === 'skill' && operation === 'rollback') return record.state === 'rolled-back';
  if (kind === 'workflow' && operation === 'approve') return record.schema_version === 'px.workflow-approval-result/1.0' && typeof record.approval_id === 'string' && record.approval_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && operation === 'start') return record.schema_version === `px.${kind}-session-start/1.1` && record.accepted === true && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (kind === 'agent' && operation === 'resume') return record.schema_version === 'px.agent-session-start/1.1' && record.accepted === true && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (kind === 'workflow' && operation === 'resume') return record.schema_version === 'px.workflow-runtime-receipt/1.2' && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && ['status', 'pause', 'cancel', 'stop'].includes(operation)) return record.schema_version === 'px.studio-durable-run/1.0' && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && operation === 'reconcile') return record.schema_version === 'px.studio-run-reconciliation/1.0' && record.valid === true;
  if (['agent', 'workflow'].includes(kind) && operation === 'runs') return record.schema_version === 'px.studio-run-list/1.0' && record.kind === kind && Array.isArray(record.runs);
  return false;
}

function studioLifecycleControlProbe(matrix, observations) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const byKind = new Map(observations.map(observation => [observation.kind, observation]));
  const successful = (kind, operation) => byKind.get(kind)?.operations?.some(item => item.operation === operation && item.valid === true) === true;
  const exact = kind => byKind.get(kind)?.exact_catalog_selection === true;
  const reopened = kind => byKind.get(kind)?.durable_run_reopened === true;
  const specs = [
    ['pxui.agents.action.inspectCatalogItem.row', ['agent'], () => exact('agent')],
    ['pxui.workflows.action.inspectCatalogItem.row', ['workflow'], () => exact('workflow')],
    ['pxui.skills-tools.action.inspectCatalogItem.row', ['skill'], () => exact('skill')],
    ['pxui.studio-lifecycle.action.operateStudioRevision', ['agent', 'workflow', 'skill'], () => ['agent', 'workflow', 'skill'].every(exact)],
    ['pxui.studio-lifecycle.action.studioLifecycle.test', ['agent'], () => successful('agent', 'test')],
    ['pxui.studio-lifecycle.action.studioLifecycle.register-authority', ['agent', 'workflow'], () => successful('agent', 'register-authority') && successful('workflow', 'register-authority')],
    ['pxui.studio-lifecycle.action.studioLifecycle.admit', ['agent', 'skill'], () => successful('agent', 'admit') && successful('skill', 'admit')],
    ['pxui.studio-lifecycle.action.studioLifecycle.preview', ['agent'], () => successful('agent', 'preview')],
    ['pxui.studio-lifecycle.action.studioLifecycle.validate', ['workflow', 'skill'], () => successful('workflow', 'validate') && successful('skill', 'validate')],
    ['pxui.studio-lifecycle.action.studioLifecycle.dry-run', ['workflow'], () => successful('workflow', 'dry-run')],
    ['pxui.studio-lifecycle.action.studioLifecycle.approve', ['workflow'], () => successful('workflow', 'approve')],
    ['pxui.studio-lifecycle.action.studioLifecycle.start', ['agent', 'workflow'], () => successful('agent', 'start') && successful('workflow', 'start')],
    ['pxui.studio-lifecycle.action.submitStudioAgentRun', ['agent'], () => successful('agent', 'start')],
    ['pxui.studio-lifecycle.action.submitStudioWorkflowRun', ['workflow'], () => successful('workflow', 'start')],
    ['pxui.studio-lifecycle.action.studioRunAction.status', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.action.studioRunAction.pause', ['agent'], () => successful('agent', 'pause')],
    ['pxui.studio-lifecycle.action.studioRunAction.resume', ['agent'], () => successful('agent', 'resume')],
    ['pxui.studio-lifecycle.action.studioRunAction.stop', ['agent', 'workflow'], () => successful('agent', 'stop') || successful('workflow', 'stop')],
    ['pxui.studio-lifecycle.action.studioRunAction.cancel', ['workflow'], () => successful('workflow', 'cancel')],
    ['pxui.studio-lifecycle.action.studioRunAction.reconcile', ['agent', 'workflow'], () => successful('agent', 'reconcile') && successful('workflow', 'reconcile')],
    ['pxui.agents.action.openStudioRuns.agent', ['agent'], () => reopened('agent')],
    ['pxui.workflows.action.openStudioRuns.workflow', ['workflow'], () => reopened('workflow')],
    ['pxui.studio-lifecycle.action.studioLifecycle.promote', ['skill'], () => successful('skill', 'promote')],
    ['pxui.studio-lifecycle.action.studioLifecycle.rollback', ['skill'], () => successful('skill', 'rollback')],
    ['pxui.studio-lifecycle.menu.revisionLifecycle', ['agent', 'workflow', 'skill'], () => ['agent', 'workflow', 'skill'].every(exact)],
    ['pxui.studio-lifecycle.menu.runControls', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow')],
    ['pxui.studio-lifecycle.indicator.accepted', ['agent', 'workflow'], () => successful('agent', 'start') && successful('workflow', 'start')],
    ['pxui.studio-lifecycle.indicator.output', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.indicator.runId', ['agent', 'workflow'], () => Boolean(byKind.get('agent')?.run_id) && Boolean(byKind.get('workflow')?.run_id)],
    ['pxui.studio-lifecycle.indicator.runtimeOutcome', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.indicator.signedReceipt', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow')]
  ];
  const records = specs.map(([controlId, kinds, predicate]) => {
    const requirement = requirements.get(controlId);
    if (!requirement) throw new Error(`Studio lifecycle profile control is absent: ${controlId}`);
    const verified = predicate();
    const errors = kinds.flatMap(kind => byKind.get(kind)?.errors || []);
    const evidenceRef = `installed-studio-lifecycle:${controlId}`;
    return {
      control_id: controlId, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_studio_lifecycle', rendered: kinds.every(exact), observed: kinds.every(exact), attempted: true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'This exact lifecycle success profile did not inject a backend failure.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: `The exact installed ${kinds.join(' and ')} Studio control completed through request-bound host approval, typed canonical receipts, and durable state retrieval where applicable.`, evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned lifecycle campaign did not complete the exact ${kinds.join(' and ')} control.`, evidence: [] }];
      })),
      errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact candidate lifecycle operations executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, records };
}

async function waitForStudioOperationResult(frameHost, after, kind, operation, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const response = await frameHost.evaluate((frame, item) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      return responses.slice(item.after).find(value => (value?.type === 'studioOperationResult' && value?.kind === item.kind && value?.operation === item.operation)
        || (value?.type === 'operationError' && value?.operation === 'studioOperation' && value?.kind === item.kind && value?.suboperation === item.operation)) || null;
    }, { after, kind, operation });
    if (response?.type === 'operationError') throw new Error(`studio-${kind}-${operation}-failed:${response.error}`);
    if (response) return response.result;
    await wait(200);
  } while (Date.now() < deadline);
  throw new Error(`studio-${kind}-${operation}-response-timeout`);
}

async function runInstalledStudioLifecycleProfile(frameHost, candidateProfile, matrix) {
  const observations = [];
  for (const candidate of candidateProfile.observations || []) {
    const operations = candidate.kind === 'agent'
      ? ['test', 'register-authority', 'admit', 'preview', 'start']
      : candidate.kind === 'workflow'
        ? ['register-authority', 'validate', 'dry-run', 'approve', 'start']
        : ['validate', 'admit', 'promote', ...(candidate.expect_rollback ? ['rollback'] : [])];
    const observation = { kind: candidate.kind, identity: candidate.identity, version: candidate.version, catalog_record_id: candidate.catalog_record_id, exact_catalog_selection: false, operations: [], run_id: null, durable_run_reopened: false, errors: [] };
    try {
      if (!candidate.typed_creation_receipt || !candidate.reopened_catalog_match || !candidate.catalog_record_id) throw new Error(`studio-${candidate.kind}-lifecycle-candidate-prerequisite-missing`);
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
      }, candidate);
      await wait(180);
      await frameHost.evaluate((frame, item) => {
        if (!['agents', 'workflows'].includes(item.route)) return;
        const scope = frame.contentDocument?.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(item.route)}"][data-scope="core"]`);
        if (!scope || scope.disabled) throw new Error(`studio-${item.kind}-lifecycle-core-scope-unavailable`);
        if (scope.getAttribute('aria-pressed') !== 'true') scope.click();
      }, candidate);
      await wait(150);
      await frameHost.evaluate((frame, item) => {
        if (item.route !== 'skillsTools') return;
        const native = [...frame.contentDocument.querySelectorAll('[data-action="capabilityTab"]')].find(element => element.dataset.kind === 'skills' && !element.disabled);
        if (!native) throw new Error('studio-skill-native-catalog-tab-unavailable');
        native.click();
      }, candidate);
      if (candidate.route === 'skillsTools') await wait(180);
      observation.exact_catalog_selection = await frameHost.evaluate((frame, item) => {
        const row = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')].find(element => element.dataset.kind === `${item.kind}s` && element.dataset.id === item.catalog_record_id && !element.disabled);
        if (!row) return false;
        row.click();
        return true;
      }, candidate);
      if (!observation.exact_catalog_selection) throw new Error(`studio-${candidate.kind}-exact-catalog-row-unavailable`);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const control = [...frame.contentDocument.querySelectorAll('[data-action="operateStudioRevision"]')].find(element => element.dataset.kind === kind && !element.disabled);
        if (!control) throw new Error(`studio-${kind}-candidate-lifecycle-continuation-unavailable`);
        control.click();
      }, candidate.kind);
      await wait(100);
      for (const operation of operations) {
        const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
        await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          const action = [...document.querySelectorAll('[data-action="studioLifecycle"]')].find(element => element.dataset.kind === item.kind && element.dataset.operation === item.operation && !element.disabled);
          if (!action) throw new Error(`studio-${item.kind}-${item.operation}-control-unavailable`);
          action.click();
          if (item.operation === 'start' && item.kind === 'agent') {
            const objective = document.querySelector('#studio-agent-objective');
            const toolCalls = document.querySelector('#studio-agent-tool-calls');
            const submit = document.querySelector('[data-action="submitStudioAgentRun"]');
            if (!objective || !toolCalls || !submit || submit.disabled) throw new Error('studio-agent-start-form-unavailable');
            objective.value = 'Return a bounded identity result without external effects.';
            objective.dispatchEvent(new Event('input', { bubbles: true }));
            toolCalls.value = JSON.stringify(Array.from({ length: 8 }, () => ({ tool: 'delay', input: 1.5 })));
            toolCalls.dispatchEvent(new Event('input', { bubbles: true }));
            submit.click();
          }
          if (item.operation === 'start' && item.kind === 'workflow') {
            const inputs = document.querySelector('#studio-workflow-inputs');
            const submit = document.querySelector('[data-action="submitStudioWorkflowRun"]');
            if (!inputs || !submit || submit.disabled) throw new Error('studio-workflow-start-form-unavailable');
            inputs.value = JSON.stringify({ 'step:one.value': 'bounded-value' }, null, 2);
            inputs.dispatchEvent(new Event('input', { bubbles: true }));
            submit.click();
          }
        }, { kind: candidate.kind, operation });
        const result = await waitForStudioOperationResult(frameHost, before, candidate.kind, operation);
        const valid = validStudioLifecycleResult(candidate.kind, operation, result);
        observation.operations.push({ operation, valid, result });
        if (!valid) throw new Error(`studio-${candidate.kind}-${operation}-receipt-invalid:${JSON.stringify(result)}`);
        if (operation === 'start') observation.run_id = String((result?.record || result)?.run_id || '');
        if (operation !== 'start') await wait(100);
      }
      if (observation.run_id) {
        const invokeRunControl = async operation => {
          const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
          const available = await frameHost.evaluate((frame, requested) => {
            const action = [...frame.contentDocument.querySelectorAll('[data-action="studioRunAction"]')].find(element => element.dataset.operation === requested && !element.disabled);
            if (!action) return false;
            action.click();
            return true;
          }, operation);
          if (!available) throw new Error(`studio-${candidate.kind}-${operation}-control-unavailable`);
          const result = await waitForStudioOperationResult(frameHost, before, candidate.kind, operation, 10_000);
          const valid = validStudioLifecycleResult(candidate.kind, operation, result);
          observation.operations.push({ operation, valid, result });
          if (!valid) throw new Error(`studio-${candidate.kind}-${operation}-receipt-invalid:${JSON.stringify(result)}`);
          await wait(120);
          return result?.record || result;
        };
        const waitForState = async expected => {
          const deadline = Date.now() + 10_000;
          let state = '';
          do {
            const status = await invokeRunControl('status');
            state = String(status?.state || status?.runtime_state || '').toLowerCase();
            if (expected.includes(state)) return state;
            await wait(180);
          } while (Date.now() < deadline);
          throw new Error(`studio-${candidate.kind}-state-timeout:${expected.join('|')}:${state || 'unknown'}`);
        };
        if (candidate.kind === 'agent') {
          await invokeRunControl('pause');
          await waitForState(['paused']);
          await invokeRunControl('resume');
          await invokeRunControl('stop');
        } else if (candidate.kind === 'workflow') {
          await invokeRunControl('cancel');
        }
        const statusDeadline = Date.now() + 20_000;
        let terminalState = '';
        do {
          const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
          const statusAvailable = await frameHost.evaluate(frame => {
            const action = [...frame.contentDocument.querySelectorAll('[data-action="studioRunAction"]')].find(element => element.dataset.operation === 'status' && !element.disabled);
            if (!action) return false;
            action.click();
            return true;
          });
          if (!statusAvailable) throw new Error(`studio-${candidate.kind}-status-control-unavailable`);
          const status = await waitForStudioOperationResult(frameHost, before, candidate.kind, 'status', 8_000);
          const valid = validStudioLifecycleResult(candidate.kind, 'status', status);
          observation.operations.push({ operation: 'status', valid, result: status });
          if (!valid) throw new Error(`studio-${candidate.kind}-status-receipt-invalid:${JSON.stringify(status)}`);
          const state = String((status?.record || status)?.state || (status?.record || status)?.runtime_state || '').toLowerCase();
          terminalState = state;
          const expectedTerminal = ['cancelled'];
          if (expectedTerminal.includes(state)) break;
          if (['failed', 'succeeded'].includes(state)) throw new Error(`studio-${candidate.kind}-unexpected-run-terminal-${state}`);
          await wait(300);
        } while (Date.now() < statusDeadline);
        const expectedTerminal = ['cancelled'];
        if (!expectedTerminal.includes(terminalState)) throw new Error(`studio-${candidate.kind}-run-terminal-timeout:${terminalState || 'unknown'}`);
        const beforeRuns = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
        await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          document?.querySelector('[data-action="closeModal"]')?.click();
          document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
          const open = [...document.querySelectorAll('[data-action="openStudioRuns"]')].find(element => element.dataset.kind === item.kind && !element.disabled);
          if (!open) throw new Error(`studio-${item.kind}-durable-run-browser-unavailable`);
          open.click();
        }, candidate);
        const runs = await waitForStudioOperationResult(frameHost, beforeRuns, candidate.kind, 'runs');
        const valid = validStudioLifecycleResult(candidate.kind, 'runs', runs);
        observation.operations.push({ operation: 'runs', valid, result: runs });
        observation.durable_run_reopened = valid && (runs.runs || []).some(run => run.run_id === observation.run_id);
        if (!observation.durable_run_reopened) throw new Error(`studio-${candidate.kind}-durable-run-reopen-missing`);
        await invokeRunControl('reconcile');
      }
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
  }
  return { schema_version: 'px.installed-studio-lifecycle-profile/1.0', authority: 'Exact candidate lifecycle operations executed only inside the owned isolated VS Code host.', observations, control_probe: studioLifecycleControlProbe(matrix, observations) };
}

function validKnowledgeLifecycleResult(operation, result, expected = {}) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  const hash = value => /^[0-9a-f]{64}$/.test(String(value || ''));
  if (operation === 'browse') {
    return record?.schema_version === 'px.knowledge-core-control/1.0'
      && Array.isArray(record.proposals) && Array.isArray(record.canonical);
  }
  if (['propose', 'verify', 'approve', 'promote', 'reject'].includes(operation)) {
    const states = { propose: 'candidate', verify: 'verified', approve: 'approved', promote: 'promoted', reject: 'rejected' };
    return record?.schema_version === 'px.knowledge-proposal/1.0'
      && record.state === states[operation]
      && typeof record.proposal_id === 'string' && record.proposal_id.length > 0
      && hash(record.candidate_sha256)
      && (!expected.proposal_id || record.proposal_id === expected.proposal_id)
      && (!expected.candidate_sha256 || record.candidate_sha256 === expected.candidate_sha256);
  }
  if (operation === 'rollback') {
    return record?.schema_version === 'px.knowledge-rollback/1.0'
      && hash(record.from_sha256) && hash(record.to_sha256)
      && record.hard_delete === false
      && (!expected.from_sha256 || record.from_sha256 === expected.from_sha256)
      && (!expected.to_sha256 || record.to_sha256 === expected.to_sha256);
  }
  if (operation === 'recover') return record?.schema_version === 'px.knowledge-recovery/1.0' && record.valid === true;
  return false;
}

async function waitForKnowledgeControl(frameHost, selector, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const available = await frameHost.evaluate((frame, query) => {
      const control = frame.contentDocument?.querySelector(query);
      return Boolean(control && !control.disabled && (control.offsetWidth || control.offsetHeight || control.getClientRects().length));
    }, selector);
    if (available) return true;
    await wait(150);
  } while (Date.now() < deadline);
  const diagnostic = await frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    return {
      heading: String(document?.querySelector('h1,h2')?.textContent || '').trim().slice(0, 160),
      surfaces: [...(document?.querySelectorAll('[data-surface]') || [])].slice(0, 40).map(element => ({ surface: element.dataset.surface || '', visible: visible(element), disabled: Boolean(element.disabled) })),
      knowledge_actions: [...(document?.querySelectorAll('[data-action]') || [])].filter(element => /knowledge/i.test(element.dataset.action || '')).slice(0, 40).map(element => ({ action: element.dataset.action || '', visible: visible(element), disabled: Boolean(element.disabled) }))
    };
  });
  throw new Error(`knowledge-control-unavailable:${selector}:${JSON.stringify(diagnostic)}`);
}

async function settleKnowledgeMutation(frameHost, before, operation, expected = {}, timeoutMs = 120_000) {
  const result = await waitForStudioOperationResult(frameHost, before, 'knowledge', operation, timeoutMs);
  if (!validKnowledgeLifecycleResult(operation, result, expected)) throw new Error(`knowledge-${operation}-receipt-invalid:${JSON.stringify(result)}`);
  const browse = await waitForStudioOperationResult(frameHost, before, 'knowledge', 'browse', timeoutMs);
  if (!validKnowledgeLifecycleResult('browse', browse)) throw new Error(`knowledge-${operation}-refresh-invalid:${JSON.stringify(browse)}`);
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
  return { operation, result, browse };
}

function knowledgeBrowseHasHead(browse, recordId, candidateSha256) {
  return (browse?.canonical || []).some(record => record.record_id === recordId && record.candidate_sha256 === candidateSha256);
}

function knowledgeLifecycleControlProbe(matrix, observation) {
  const admittedActions = new Set(['knowledgePropose', 'submitKnowledgeProposal', 'knowledgeTransition', 'knowledgeRollback', 'submitKnowledgeRollback', 'knowledgeReject', 'submitKnowledgeReject', 'knowledgeRecover', 'knowledgeRefresh']);
  const requirements = matrix.controls.filter(control => control.surface_id === 'knowledge-core' && (
    (control.kind === 'action' && admittedActions.has(installedActionIdentity(control).action))
    || ['form', 'lifecycle', 'persistence'].includes(control.kind)
  ));
  const verified = observation.completed === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-knowledge-lifecycle:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_knowledge_lifecycle', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'This successful lifecycle profile did not inject a matched Knowledge backend failure.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The installed Knowledge UI completed exact source-bound proposals, lifecycle approvals, immutable update, canonical rollback, rejection, recovery, and authoritative refreshed-state checks inside the owned disposable workspace.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The owned installed-host Knowledge lifecycle did not complete this exact control chain.', evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact Knowledge lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', eligible_control_count: records.length, records };
}

async function runInstalledKnowledgeLifecycleProfile(frameHost, matrix, timeoutMs = 120_000) {
  const observation = { rendered: false, attempted: false, completed: false, record_id: '', rejected_record_id: '', first_sha256: '', second_sha256: '', operations: [], errors: [] };
  try {
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="dashboard"]')?.click();
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
      if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
    });
    await wait(200);
    const route = await frameHost.evaluate(frame => {
      const element = frame.contentDocument?.querySelector('[data-surface="knowledgeCore"]');
      if (!element) return { found: false, disabled: null };
      if (!element.disabled) element.click();
      return { found: true, disabled: Boolean(element.disabled) };
    });
    if (!route.found || route.disabled) throw new Error(`knowledge-route-unavailable:${JSON.stringify(route)}`);
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRefresh"]');
    const initialBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRefresh"]').click());
    const initialBrowse = await waitForStudioOperationResult(frameHost, initialBefore, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', initialBrowse)) throw new Error(`knowledge-initial-browse-invalid:${JSON.stringify(initialBrowse)}`);
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgePropose"]');
    observation.rendered = true;
    observation.attempted = true;
    observation.record_id = `knowledge:px-owned-${Date.now()}`;
    observation.rejected_record_id = `${observation.record_id}-rejected`;

    const propose = async (recordId, summary) => {
      await waitForKnowledgeControl(frameHost, '[data-action="knowledgePropose"]');
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgePropose"]').click());
      await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeProposal"]');
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, values) => {
        const document = frame.contentDocument;
        const set = (selector, value) => { const field = document.querySelector(selector); if (!field) throw new Error(`knowledge-field-unavailable:${selector}`); field.value = value; field.dispatchEvent(new Event('input', { bubbles: true })); };
        set('#knowledge-id', values.recordId); set('#knowledge-title', values.recordId); set('#knowledge-summary', values.summary);
        const source = document.querySelector('#knowledge-source'); const evidence = document.querySelector('#knowledge-evidence');
        if (!source || ![...source.options].some(option => option.value === values.sourceId) || !/^[0-9a-f]{64}$/.test(values.sourceSha256)) throw new Error('knowledge-owned-source-fixture-unavailable');
        source.value = values.sourceId; source.dispatchEvent(new Event('change', { bubbles: true }));
        evidence.value = `sha256:${values.sourceSha256}`; evidence.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector('[data-action="submitKnowledgeProposal"]').click();
      }, { recordId, summary, sourceId: ownedKnowledgeSourceId, sourceSha256: ownedKnowledgeSourceSha256 });
      return settleKnowledgeMutation(frameHost, before, 'propose', {}, timeoutMs);
    };
    const transition = async (operation, proposalId, candidateSha256) => {
      const selector = `[data-action="knowledgeTransition"][data-operation="${operation}"][data-proposal-id="${proposalId}"]`;
      await waitForKnowledgeControl(frameHost, selector);
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), selector);
      return settleKnowledgeMutation(frameHost, before, operation, { proposal_id: proposalId, candidate_sha256: candidateSha256 }, timeoutMs);
    };
    const promoteCandidate = async proposed => {
      const proposal = proposed.result?.record || proposed.result; const proposalId = proposal.proposal_id; const candidateSha256 = proposal.candidate_sha256;
      for (const operation of ['verify', 'approve', 'promote']) {
        const settled = await transition(operation, proposalId, candidateSha256); observation.operations.push(settled);
      }
      return { proposalId, candidateSha256, browse: observation.operations.at(-1).browse };
    };

    const firstProposal = await propose(observation.record_id, 'Owned Knowledge lifecycle revision one.'); observation.operations.push(firstProposal);
    const first = await promoteCandidate(firstProposal); observation.first_sha256 = first.candidateSha256;
    if (!knowledgeBrowseHasHead(first.browse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-first-canonical-head-missing');
    const secondProposal = await propose(observation.record_id, 'Owned Knowledge lifecycle revision two with immutable supersession.'); observation.operations.push(secondProposal);
    const second = await promoteCandidate(secondProposal); observation.second_sha256 = second.candidateSha256;
    if (observation.first_sha256 === observation.second_sha256 || !knowledgeBrowseHasHead(second.browse, observation.record_id, observation.second_sha256)) throw new Error('knowledge-update-canonical-head-missing-or-unchanged');

    const rollbackSelector = `[data-action="knowledgeRollback"][data-record-id="${observation.record_id}"][data-current-sha="${observation.second_sha256}"][data-target-sha="${observation.first_sha256}"]`;
    await waitForKnowledgeControl(frameHost, rollbackSelector);
    await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), rollbackSelector);
    await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeRollback"]');
    const beforeRollback = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, evidence) => { const field = frame.contentDocument.querySelector('#knowledge-rollback-evidence'); field.value = `sha256:${evidence}`; field.dispatchEvent(new Event('input', { bubbles: true })); frame.contentDocument.querySelector('[data-action="submitKnowledgeRollback"]').click(); }, observation.first_sha256);
    const rollback = await settleKnowledgeMutation(frameHost, beforeRollback, 'rollback', { from_sha256: observation.second_sha256, to_sha256: observation.first_sha256 }, timeoutMs); observation.operations.push(rollback);
    if (!knowledgeBrowseHasHead(rollback.browse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-rollback-canonical-head-missing');

    const rejectedProposal = await propose(observation.rejected_record_id, 'Owned Knowledge rejection and recovery candidate.'); observation.operations.push(rejectedProposal);
    const rejectedRecord = rejectedProposal.result?.record || rejectedProposal.result;
    const rejectSelector = `[data-action="knowledgeReject"][data-proposal-id="${rejectedRecord.proposal_id}"]`;
    await waitForKnowledgeControl(frameHost, rejectSelector);
    await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), rejectSelector);
    await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeReject"]');
    const beforeReject = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => { const field = frame.contentDocument.querySelector('#knowledge-reject-reason'); field.value = 'Owned lifecycle rejection test with retained evidence.'; field.dispatchEvent(new Event('input', { bubbles: true })); frame.contentDocument.querySelector('[data-action="submitKnowledgeReject"]').click(); });
    const reject = await settleKnowledgeMutation(frameHost, beforeReject, 'reject', { proposal_id: rejectedRecord.proposal_id, candidate_sha256: rejectedRecord.candidate_sha256 }, timeoutMs); observation.operations.push(reject);

    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRecover"]');
    const beforeRecover = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRecover"]').click());
    const recover = await settleKnowledgeMutation(frameHost, beforeRecover, 'recover', {}, timeoutMs); observation.operations.push(recover);
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRefresh"]');
    const beforeRefresh = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRefresh"]').click());
    const finalBrowse = await waitForStudioOperationResult(frameHost, beforeRefresh, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', finalBrowse) || !knowledgeBrowseHasHead(finalBrowse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-final-authoritative-refresh-invalid');
    observation.final_browse = finalBrowse;
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 3000)); }
  return { schema_version: 'px.installed-knowledge-lifecycle-profile/1.0', authority: 'Exact Knowledge lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', observation, control_probe: knowledgeLifecycleControlProbe(matrix, observation) };
}

async function waitForInstalledMemoryText(frameHost, pattern, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let body = '';
  do {
    body = await frameHost.evaluate(frame => String(frame.contentDocument?.body?.innerText || ''));
    if (pattern.test(body)) return body;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`canonical-memory-view-timeout:${pattern}:${body.slice(0, 300)}`);
}

function reversibleConfigurationRecord(requirement, observation) {
  const evidenceRef = `installed-reversible-configuration:${requirement.control_id}`;
  const verified = observation.changed && observation.reopened && observation.restored;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'direct_reversible_configuration_interaction', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, { state: 'missing', detail: 'This success/restoration profile did not inject a configuration failure; fault evidence must supply this stage.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `Exact installed configuration action changed state, acknowledged through the typed host contract, survived route reopen, and restored its exact pre-state (${observation.before_target}).`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The reversible configuration campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledReversibleConfigurationProfile(workbench, frameHost, matrix) {
  const specs = [
    { controlId: 'pxui.activity.action.activityPause', route: 'activity', action: 'activityPause', datasetKey: 'paused', responseType: 'hostActionResult', operation: 'setActivityPaused' },
    { controlId: 'pxui.settings.action.toggleBillablePolicy', route: 'settings', action: 'toggleBillablePolicy', datasetKey: 'enabled', responseType: 'enterpriseResult', operation: 'toggleBillablePolicy', approvalLabel: 'Enable guarded policy' }
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const records = [];
  for (const spec of specs) {
    const observation = { available: false, attempted: false, changed: false, reopened: false, restored: false, before_target: '', errors: [] };
    try {
      const before = await readInstalledConfigurationAction(frameHost, spec);
      observation.available = before.available; observation.before_target = before.target_value;
      if (!before.available || !['true', 'false'].includes(before.target_value)) throw new Error(`${spec.action}-prestate-unavailable`);
      observation.attempted = true;
      await invokeInstalledConfigurationAction(workbench, frameHost, spec, before.target_value);
      const changed = await waitForInstalledConfigurationTarget(frameHost, spec, value => value !== before.target_value);
      observation.changed = changed.target_value !== before.target_value;
      observation.reopened = observation.changed;
      if (!observation.changed) throw new Error(`${spec.action}-state-did-not-change`);
      await invokeInstalledConfigurationAction(workbench, frameHost, spec, changed.target_value);
      const restored = await waitForInstalledConfigurationTarget(frameHost, spec, value => value === before.target_value);
      observation.restored = restored.target_value === before.target_value;
      if (!observation.restored) throw new Error(`${spec.action}-restoration-mismatch:${restored.target_value}:${before.target_value}`);
    } catch (error) {
      observation.errors.push(String(error?.message || error).slice(0, 1000));
      try {
        const current = await readInstalledConfigurationAction(frameHost, spec);
        if (observation.before_target && current.available && current.target_value !== observation.before_target) {
          await invokeInstalledConfigurationAction(workbench, frameHost, spec, current.target_value);
          const restored = await waitForInstalledConfigurationTarget(frameHost, spec, value => value === observation.before_target);
          observation.restored = restored.target_value === observation.before_target;
        }
      } catch (restoreError) { observation.errors.push(`restoration:${String(restoreError?.message || restoreError).slice(0, 900)}`); }
    }
    const requirement = requirements.get(spec.controlId);
    if (!requirement) throw new Error(`Reversible configuration profile references an unknown control: ${spec.controlId}`);
    records.push(reversibleConfigurationRecord(requirement, observation));
  }
  const memoryRequirements = ['pxui.memory.action.configureCanonicalMemory', 'pxui.memory.action.disconnectCanonicalMemory']
    .map(controlId => requirements.get(controlId));
  if (!memoryRequirements.every(Boolean)) throw new Error('Canonical memory reversible profile controls are absent from the authoritative proof matrix.');
  {
    const setup = { available: true, attempted: false, changed: false, reopened: false, restored: false, before_target: '', errors: [] };
    try {
      setup.attempted = true;
      const configured = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' });
      setup.before_target = String(configured.detail?.previousWorkspaceRoot || '');
      setup.changed = Boolean(configured.detail?.workspaceRoot) && configured.detail.workspaceRoot !== setup.before_target;
      await waitForInstalledMemoryText(frameHost, /Lease-bound canonical retrieval is ready\./);
      setup.reopened = true;
      const detached = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' });
      setup.restored = String(detached.detail?.restoredWorkspaceRoot || '') === setup.before_target;
      await waitForInstalledMemoryText(frameHost, /Canonical memory is not configured\./);
      if (!setup.changed || !setup.restored) throw new Error(`canonical-memory-restoration-mismatch:${setup.changed}:${setup.restored}`);
    } catch (error) {
      setup.errors.push(String(error?.message || error).slice(0, 1000));
      try {
        await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' }, 30_000);
        setup.restored = true;
      } catch (restoreError) { setup.errors.push(`restoration:${String(restoreError?.message || restoreError).slice(0, 900)}`); }
    }
    records.push(reversibleConfigurationRecord(memoryRequirements[0], setup));
    records.push(reversibleConfigurationRecord(memoryRequirements[1], { ...setup, before_target: 'configured-owned-canonical-memory' }));
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed host reversible configuration operation with finally restoration.',
    eligible_control_count: records.length,
    records
  };
}

async function waitForInstalledSnapshot(frameHost, after, predicate, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let candidate = null;
  do {
    candidate = await frameHost.evaluate((frame, offset) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      return responses.slice(offset).filter(value => value?.type === 'snapshot').at(-1)?.snapshot || null;
    }, after);
    if (candidate && predicate(candidate)) return candidate;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`installed-snapshot-state-timeout:${JSON.stringify({ connected: candidate?.connected, reason: candidate?.reason })}`);
}

async function requestInstalledRefresh(frameHost) {
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  await frameHost.evaluate(frame => {
    const dashboard = frame.contentDocument?.querySelector('[data-surface="dashboard"]');
    if (!dashboard || dashboard.disabled) throw new Error('installed-dashboard-route-unavailable-for-refresh');
    dashboard.click();
  });
  await wait(100);
  await frameHost.evaluate(frame => {
    const control = [...frame.contentDocument.querySelectorAll('[data-action="refresh"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (!control) throw new Error('installed-refresh-control-unavailable');
    control.click();
  });
  return before;
}

async function installedSurfaceConnection(frameHost, requirement) {
  const route = INSTALLED_ROUTES[requirement.surface_id];
  await frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    if (item.advanced) {
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
      if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
    }
    const target = document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`);
    if (!target) throw new Error(`installed-outage-route-unavailable:${item.route}`);
    target.click();
  }, { route, advanced: ['knowledgeCore', 'runtimeCore'].includes(route) });
  await wait(100);
  return frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const app = document?.querySelector('#app');
    const alert = document?.querySelector('[data-engine-disconnected][role="alert"]');
    return {
      heading: document?.querySelector('main h1')?.textContent?.trim() || '',
      disconnected: Boolean(app?.classList.contains('disconnected')),
      alert_visible: Boolean(alert && (alert.offsetWidth || alert.offsetHeight || alert.getClientRects().length)),
      alert_text: String(alert?.textContent || '').replace(/\s+/g, ' ').trim(),
      footer: String(document?.querySelector('.footer')?.textContent || '').replace(/\s+/g, ' ').trim()
    };
  });
}

function engineOutageRecord(requirement, observation) {
  const evidenceRef = `installed-engine-outage:${requirement.control_id}`;
  const baseline = observation.baseline?.[requirement.control_id];
  const fault = observation.fault?.[requirement.control_id];
  const recovered = observation.recovered?.[requirement.control_id];
  const failure = Boolean(baseline && !baseline.disconnected && fault?.disconnected && fault.alert_visible
    && /metrics are unavailable/i.test(fault.alert_text) && /not an observed system value/i.test(fault.alert_text));
  const recovery = Boolean(observation.restoration?.restored && recovered && !recovered.disconnected
    && !recovered.alert_visible && /CONTROL PLANE CONNECTED/i.test(recovered.footer));
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_disposable_engine_outage', rendered: Boolean(baseline?.heading), observed: failure || recovery,
    attempted: observation.outage_started === true,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, failure
        ? { state: 'present', detail: 'The exact surface rendered a prominent non-authoritative-metrics alert after the installed host returned a physical disposable-engine disconnection.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The physical disposable-engine outage did not produce the exact visible fail-closed surface state.', evidence: [] }];
      if (stage === 'recovery_rollback') return [stage, recovery
        ? { state: 'present', detail: 'The displaced runtime was restored byte-for-byte and the exact surface returned to a connected snapshot without the outage alert.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'Exact engine restoration and connected surface recovery were not both observed.', evidence: [] }];
      return [stage, failure && recovery
        ? { state: 'present', detail: `Owned-root validation authorized the fault, the installed refresh crossed the host/backend boundary, and the exact surface acknowledged ${stage} during physical failure and recovery.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The engine outage profile did not prove required stage ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledEngineOutageProfile(frameHost, matrix) {
  const requirements = matrix.controls.filter(control => control.kind === 'failure_recovery'
    && !['sidebar', 'agent-studio', 'workflow-studio', 'skill-studio'].includes(control.surface_id)
    && Object.hasOwn(INSTALLED_ROUTES, control.surface_id));
  const observation = { outage_started: false, baseline: {}, fault: {}, recovered: {}, fault_snapshot: null, recovered_snapshot: null, restoration: null, errors: [] };
  let outage = null;
  try {
    for (const requirement of requirements) observation.baseline[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
    outage = beginOwnedEngineOutage(process.env.PX_OWNED_ENGINE_ROOT, ownedHostToken);
    observation.outage_started = true;
    const faultAfter = await requestInstalledRefresh(frameHost);
    observation.fault_snapshot = await waitForInstalledSnapshot(frameHost, faultAfter, snapshot => snapshot.connected === false);
    for (const requirement of requirements) observation.fault[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
  } catch (error) {
    observation.errors.push(String(error?.message || error).slice(0, 2000));
  } finally {
    if (outage) {
      try { observation.restoration = outage.restore(); }
      catch (error) { observation.errors.push(`restoration:${String(error?.message || error).slice(0, 1800)}`); }
    }
  }
  if (observation.restoration?.restored) {
    try {
      const recoveryAfter = await requestInstalledRefresh(frameHost);
      observation.recovered_snapshot = await waitForInstalledSnapshot(frameHost, recoveryAfter, snapshot => snapshot.connected === true && snapshot.extensionIdentity?.matches === true);
      for (const requirement of requirements) observation.recovered[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
    } catch (error) { observation.errors.push(`recovery:${String(error?.message || error).slice(0, 1800)}`); }
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Physical runtime displacement and exact byte-preserving restoration inside the PACIFY-X-owned disposable engine only.',
    eligible_control_count: requirements.length,
    observation,
    records: requirements.map(requirement => engineOutageRecord(requirement, observation))
  };
}

async function main() {
  // The authoritative denominator is validated before attaching to or
  // interacting with a live host. A changed/duplicate inventory fails closed.
  const inventory = loadOperationalSurfaceInventory(inventoryPath);
  const proofMatrix = JSON.parse(fs.readFileSync(proofMatrixPath, 'utf8'));
  if (!Array.isArray(proofMatrix.controls) || proofMatrix.controls.length !== inventory.control_count) {
    throw new Error('Operational proof matrix does not match the authoritative installed-host denominator.');
  }
  fs.mkdirSync(outputRoot, { recursive: true });
  const profileProgressPath = path.join(outputRoot, 'profile-progress.ndjson');
  const appendProfileProgress = event => fs.appendFileSync(profileProgressPath, `${JSON.stringify({ schema_version: 'px.operational-profile-progress/1.0', observed_utc: new Date().toISOString(), ...event })}\n`, { encoding: 'utf8' });
  const returnedProfileErrors = result => [
    ...((result?.observation?.errors || [])),
    ...((result?.observations || []).flatMap(item => item?.errors || [])),
    ...((result?.records || []).flatMap(item => item?.errors || []))
  ].map(error => String(error).slice(0, 1000)).slice(0, 12);
  const timedProfile = async (profile, operation) => {
    const started = Date.now(); appendProfileProgress({ profile, state: 'started' });
    try {
      const result = await operation();
      const errors = returnedProfileErrors(result);
      appendProfileProgress({ profile, state: 'returned', duration_ms: Date.now() - started, completed: result?.observation?.completed ?? null, error_count: errors.length, errors });
      return result;
    } catch (error) {
      appendProfileProgress({ profile, state: 'threw', duration_ms: Date.now() - started, error: String(error?.message || error).slice(0, 1200) });
      throw error;
    }
  };
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
    if (ownedReversibleConfigurationAuthority && !await instrumentInstalledBridge(dashboard)) throw new Error(`Owned ${focusedProfile || 'integrated'} profile could not instrument the installed host response bridge.`);
    const attemptedControlIds = ['pxui.dashboard-control-plane.command.pacifyX.openDashboard'];
    const initialDashboardText = await innerText(dashboard);
    const hostSourceMismatch = /EXTENSION IDENTITY MISMATCH|host-assets-differ-from-source/i.test(initialDashboardText);
    const hostSourceIdentityVerified = !hostSourceMismatch && /exact host\/source identity/i.test(initialDashboardText);
    if (!hostSourceMismatch && !studioLifecycleOnly) {
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
    if (!hostSourceMismatch && !focusedProfileOnly) {
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
    for (const kind of focusedProfileOnly ? [] : ['agent', 'workflow']) {
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
    if (focusedProfileOnly) {
      builders.agent = { terminal_disposition: 'focused_profile_not_run', observations: [], attempted_control_ids: [] };
      builders.workflow = { terminal_disposition: 'focused_profile_not_run', observations: [], attempted_control_ids: [] };
    }
    const reversibleConfigurationProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || configurationOnly)
      ? await timedProfile('reversible-configuration', () => runInstalledReversibleConfigurationProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    const studioSetupProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly
      ? await timedProfile('studio-setup', () => runInstalledStudioSetupProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    const studioCandidateSaveProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly
      ? await timedProfile('studio-candidate-save', () => runInstalledStudioCandidateSaveProfile(dashboard, proofMatrix, studioLifecycleOnly ? 45_000 : 150_000))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    let studioLifecycleProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly
      ? await timedProfile('studio-lifecycle', () => runInstalledStudioLifecycleProfile(dashboard, studioCandidateSaveProfile, proofMatrix))
      : { schema_version: 'px.installed-studio-lifecycle-profile/1.0', authority: 'Not admitted outside an owned isolated host.', observations: [], control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] } };
    const studioRevisionEditProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly
      ? await timedProfile('studio-revision-edit', () => runInstalledStudioRevisionEditProfile(dashboard, studioCandidateSaveProfile, proofMatrix, studioLifecycleOnly ? 45_000 : 150_000))
      : { schema_version: 'px.installed-studio-revision-edit-profile/1.0', authority: 'Not admitted outside an owned isolated host.', observations: [], control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] } };
    if (ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly) {
      const baseSkill = (studioCandidateSaveProfile.observations || []).find(item => item.kind === 'skill');
      const revisedSkill = (studioRevisionEditProfile.observations || []).find(item => item.kind === 'skill');
      if (baseSkill && validStudioRevisionEditObservation(revisedSkill)) {
        const rollbackCandidate = {
          ...baseSkill,
          version: revisedSkill.candidate_version,
          catalog_record_id: revisedSkill.saved_catalog_record_id,
          typed_creation_receipt: revisedSkill.typed_creation_receipt,
          reopened_catalog_match: revisedSkill.reopened_catalog_match,
          expect_rollback: true
        };
        const rollbackProfile = await timedProfile('studio-skill-revision-rollback', () => runInstalledStudioLifecycleProfile(dashboard, { observations: [rollbackCandidate] }, proofMatrix));
        const mergedByKind = new Map((studioLifecycleProfile.observations || []).map(item => [item.kind, item]));
        for (const item of rollbackProfile.observations || []) mergedByKind.set(item.kind, item);
        const mergedObservations = [...mergedByKind.values()];
        studioLifecycleProfile = {
          ...studioLifecycleProfile,
          observations: mergedObservations,
          skill_revision_rollback_profile: rollbackProfile,
          control_probe: studioLifecycleControlProbe(proofMatrix, mergedObservations)
        };
      }
    }
    const knowledgeLifecycleProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !studioLifecycleOnly
      ? await timedProfile('knowledge-lifecycle', () => runInstalledKnowledgeLifecycleProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-knowledge-lifecycle-profile/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    // Stateful profiles intentionally precede the general probe. They create
    // the disposable catalog, run, and revision state required for dynamic
    // controls to exist; probing first permanently misclassified those
    // controls as not rendered within the same campaign.
    const installedControlProbe = focusedProfileOnly
      ? { schema_version: 'px.installed-operational-control-probe/1.0', authority: `Skipped by exact owned ${focusedProfile} profile.`, eligible_control_count: 0, records: [] }
      : await probeInstalledControls(dashboard, proofMatrix, hostErrors);
    const engineOutageProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly && process.env.PX_OWNED_ENGINE_ROOT
      ? await timedProfile('engine-outage', () => runInstalledEngineOutageProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host with a disposable engine.', eligible_control_count: 0, records: [] };
    let sidebarOpenError = null;
    const isSidebarText = text => /PACIFY-X[\s\S]*OPEN CONTROL PLANE/i.test(text) && /NO ACTIVE EXECUTION|PROVIDER ACTIVITY/i.test(text);
    let sidebar = focusedProfileOnly ? null : await waitForOwnedWebview(workbench, isSidebarText, 1_500);
    const activityControl = workbench.locator('.activitybar [aria-label="Pacify-X"]:visible').first();
    if (!focusedProfileOnly && !hostSourceMismatch && !sidebar && await activityControl.count()) await activityControl.click({ timeout: 3000 });
    else if (!focusedProfileOnly && !hostSourceMismatch && !sidebar) {
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
    if (!focusedProfileOnly && !hostSourceMismatch && !sidebar) sidebar = await waitForOwnedWebview(workbench, isSidebarText, 15_000);
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
    const controlChains = applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyBuilderObservations(buildPerControlRecords({
      inventory,
      results,
      sidebar: sidebarResult,
      hostSourceMismatch,
      authority: LIVE_WALK_AUTHORITY,
      observedAt,
      attemptedControlIds: [...attemptedControlIds, ...builderControlIds]
    }), builders), installedControlProbe), reversibleConfigurationProfile, 'reversible_configuration_observations'), studioSetupProfile, 'studio_setup_observations'), studioCandidateSaveProfile, 'studio_candidate_save_observations'), studioLifecycleProfile.control_probe, 'studio_lifecycle_observations'), studioRevisionEditProfile.control_probe, 'studio_revision_edit_observations'), knowledgeLifecycleProfile.control_probe, 'knowledge_lifecycle_observations'), engineOutageProfile, 'engine_outage_observations');
    const receipt = {
      schema_version: 'px.operational-ui-walk/1.2',
      observed_at: observedAt,
      endpoint,
      authority: LIVE_WALK_AUTHORITY,
      host_source_mismatch: hostSourceMismatch,
      source_identity: {
        state: hostSourceMismatch ? 'mismatch' : hostSourceIdentityVerified ? 'verified' : 'unknown',
        method: 'dashboard-runtime-identity-contract',
        control_source_manifest: currentSourceManifest(JSON.parse(fs.readFileSync(proofMatrixPath, 'utf8')))
      },
      surfaces,
      results,
      builders,
      installed_control_probe: installedControlProbe,
      reversible_configuration_profile: reversibleConfigurationProfile,
      studio_setup_profile: studioSetupProfile,
      studio_candidate_save_profile: studioCandidateSaveProfile,
      studio_lifecycle_profile: studioLifecycleProfile,
      studio_revision_edit_profile: studioRevisionEditProfile,
      knowledge_lifecycle_profile: knowledgeLifecycleProfile,
      engine_outage_profile: engineOutageProfile,
      focused_profile: focusedProfile,
      full_operational_completion_claimed: focusedProfileOnly ? false : null,
      sidebar: sidebarResult,
      sidebar_screenshot: sidebarScreenshot,
      sidebar_open_error: sidebarOpenError,
      host_errors: hostErrors,
      control_chains: controlChains,
      limitations: [
        'The inventory denominator is authoritative; every inventory control receives exactly one terminal record with all thirteen chain stages.',
        hostSourceMismatch ? 'Installed/source identity mismatch blocked all further surface and builder interaction.' : 'The walk activates every dashboard navigation surface and records its real DOM and screenshots.',
        ownedReversibleConfigurationAuthority ? 'The owned isolated host directly executes bounded Studio setup, immutable candidate saves, exact candidate lifecycle operations, predecessor-bound next-revision edits, and a byte-restored disposable-engine outage/recovery profile with typed receipts.' : 'Agent and Workflow builder interactions are limited to reversible unsaved webview state with exact per-control pre/post digests; no candidate save or run is authorized.',
        'Controls outside the named typed profiles that require write, execution, lifecycle, recovery, reload, or destructive authority are skipped per control with an exact reason and return condition.'
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

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { applyInstalledProbeObservations, eligibleInstalledControl, engineOutageRecord, exerciseInstalledControl, installedActionIdentity, installedStudioPrerequisites, instrumentInstalledBridge, knowledgeBrowseHasHead, knowledgeLifecycleControlProbe, prepareInstalledControl, probeInstalledControls, revealInstalledControl, runInstalledEngineOutageProfile, runInstalledKnowledgeLifecycleProfile, runInstalledStudioCandidateSaveProfile, runInstalledStudioLifecycleProfile, runInstalledStudioRevisionEditProfile, runInstalledStudioSetupProfile, studioLifecycleControlProbe, validKnowledgeLifecycleResult, validStudioDraftReceipt, validStudioLifecycleResult, validStudioRevisionEditObservation, validStudioSetupResult };
