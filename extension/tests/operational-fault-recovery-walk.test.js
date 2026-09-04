'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { failureContained, recoveryObserved, stageMap } = require('../scripts/run-operational-fault-recovery-walk');
const { STAGES, currentSourceManifest } = require('../scripts/run-exhaustive-operational-control-walk');
const {
  bindCurrentWorkbenchCommandRejection,
  ensureInstalledSensorRowSnapshot,
  executeWorkbenchCommand,
  observeCurrentWorkbenchCommandRejection,
  reopenPacifyDashboardFromOwnedUi
} = require('../scripts/run-operational-ui-walk');

test('fault evidence rejects page errors and unchanged stale success', () => {
  const base = { baselineVisible: true, baselineText: '7 runnable agents', faultVisible: true, faultText: '7 runnable agents', mainVisible: true, alertText: '', newPageErrors: 0 };
  assert.equal(failureContained(base), false);
  assert.equal(failureContained({ ...base, newPageErrors: 1, faultVisible: false }), false);
});

test('fault evidence accepts exact disappearance, changed fallback, or a visible alert', () => {
  const base = { baselineVisible: true, baselineText: 'healthy', faultVisible: true, faultText: 'unavailable', mainVisible: true, alertText: '', newPageErrors: 0 };
  assert.equal(failureContained(base), true);
  assert.equal(failureContained({ ...base, faultVisible: false }), true);
  assert.equal(failureContained({ ...base, faultText: 'healthy', alertText: 'snapshot unavailable' }), true);
});

test('recovery and stage mapping remain exact and fail closed', () => {
  assert.equal(recoveryObserved({ baselineVisible: true, recoveredVisible: true, newPageErrors: 0 }), true);
  assert.equal(recoveryObserved({ baselineVisible: true, recoveredVisible: false, newPageErrors: 0 }), false);
  const control = { stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['failure_handling', 'recovery_rollback'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) };
  const stages = stageMap(control, true, false, 'receipt:demo');
  assert.equal(stages.failure_handling.state, 'present');
  assert.equal(stages.recovery_rollback.state, 'missing');
  assert.equal(stages.runtime_effect.state, 'not_applicable');
});

test('control source manifest changes when an exercised source changes', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-control-source-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'surface.js'), 'first');
  const matrix = { controls: [{ source_refs: ['surface.js:1-2'] }] };
  const before = currentSourceManifest(matrix, root);
  fs.writeFileSync(path.join(root, 'surface.js'), 'second');
  const after = currentSourceManifest(matrix, root);
  assert.notEqual(before.source_sha256, after.source_sha256);
  assert.equal(after.files[0].path, 'surface.js');
});

test('workbench command execution retries the palette through the stable F1 and keybinding paths', async () => {
  let visibleWaits = 0;
  const shortcuts = [];
  const typed = [];
  const widget = {
    async isVisible() { return visibleWaits >= 2; },
    async waitFor(options) {
      if (options.state === 'hidden') return;
      visibleWaits += 1;
      if (visibleWaits === 1) throw new Error('transient-focus-loss');
    },
    locator(selector) {
      if (selector === 'input') {
        return { first: () => ({ async getAttribute(name) { assert.equal(name, 'aria-activedescendant'); return 'px-open-control-plane'; } }) };
      }
      assert.equal(selector, '.quick-input-list .monaco-list-row');
      return {
        async evaluateAll() {
          return [{ id: 'px-open-control-plane', label: 'Pacify-X: Open Control Plane', visible: true, selected: true }];
        }
      };
    },
    async innerText() { return ''; }
  };
  const workbench = {
    async bringToFront() {},
    keyboard: {
      async press(value) { shortcuts.push(value); },
      async type(value) { typed.push(value); }
    },
    locator(selector) {
      if (selector === '.quick-input-widget:visible') return { first: () => widget };
      assert.equal(selector, '.monaco-workbench');
      return { async focus() {} };
    }
  };
  const result = await executeWorkbenchCommand(workbench, 'Pacify-X: Open Control Plane');
  assert.equal(result.executed, true);
  assert.deepEqual(shortcuts.filter(value => value !== 'Escape'), [
    'F1', process.platform === 'darwin' ? 'Meta+Shift+P' : 'Control+Shift+P',
    process.platform === 'darwin' ? 'Meta+A' : 'Control+A', 'Enter'
  ]);
  assert.deepEqual(typed, ['>Pacify-X: Open Control Plane']);
});

test('workbench rejection binds only the exact current visible focused input without retaining a locator', async t => {
  let listener = null;
  const input = {
    offsetWidth: 120, offsetHeight: 24, hidden: false,
    getAttribute() { return null; },
    getClientRects() { return [1]; }
  };
  const widget = {
    offsetWidth: 300, offsetHeight: 220, hidden: false,
    getAttribute() { return null; },
    getClientRects() { return [1]; },
    querySelector(selector) { assert.equal(selector, 'input'); return input; },
    contains(target) { return target === input; }
  };
  const originalDocument = global.document;
  const originalStyle = global.getComputedStyle;
  const originalAddEventListener = global.addEventListener;
  const originalRemoveEventListener = global.removeEventListener;
  t.after(() => {
    global.document = originalDocument;
    global.getComputedStyle = originalStyle;
    global.addEventListener = originalAddEventListener;
    global.removeEventListener = originalRemoveEventListener;
    delete global.__PX_OWNED_WORKBENCH_COMMAND_REJECTION__;
  });
  global.document = {
    activeElement: input,
    querySelectorAll(selector) { assert.equal(selector, '.quick-input-widget'); return [widget]; }
  };
  global.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
  global.addEventListener = (type, handler, options) => {
    assert.equal(type, 'keydown');
    assert.deepEqual(options, { capture: true, once: true });
    listener = handler;
  };
  global.removeEventListener = (type, handler, capture) => {
    assert.equal(type, 'keydown');
    assert.equal(handler, listener);
    assert.equal(capture, true);
  };
  const workbench = { async evaluate(operation, argument) { return operation(argument); } };
  const bound = await bindCurrentWorkbenchCommandRejection(workbench);
  assert.equal(bound.bound, true);
  assert.equal(bound.reason, 'exact-current-focused-input-window-capture');
  assert.equal(typeof bound.token, 'string');
  assert.ok(bound.token.length > 0);
  let prevented = false;
  let propagationStopped = false;
  let stopped = false;
  listener({
    key: 'Enter', target: input,
    preventDefault() { prevented = true; },
    stopPropagation() { propagationStopped = true; },
    stopImmediatePropagation() { stopped = true; }
  });
  assert.equal(prevented, true);
  assert.equal(propagationStopped, true);
  assert.equal(stopped, true);
  assert.deepEqual(await observeCurrentWorkbenchCommandRejection(workbench, bound.token), {
    rejected: true, reason: 'exact-current-focused-input-enter-rejected'
  });
});

test('sensor row preparation requests and awaits one typed snapshot before accepting the exact row', async () => {
  let sensorVisible = false;
  let refreshClicks = 0;
  const responses = [];
  const sensor = { disabled: false, offsetWidth: 180, offsetHeight: 30, getClientRects() { return [1]; } };
  const refresh = {
    disabled: false, hidden: false, offsetWidth: 80, offsetHeight: 24,
    getAttribute() { return null; }, getClientRects() { return [1]; },
    click() { refreshClicks += 1; sensorVisible = true; responses.push({ type: 'snapshot' }); }
  };
  const frame = {
    contentDocument: {
      querySelector(selector) { return selector === '[data-action="inspectSensor"][data-sensor-id]' && sensorVisible ? sensor : null; },
      querySelectorAll(selector) { assert.equal(selector, '[data-action="refresh"]'); return [refresh]; }
    },
    contentWindow: { __PX_INSTALLED_RESPONSES__: responses }
  };
  const frameHost = { async evaluate(operation, argument) { return operation(frame, argument); } };
  assert.deepEqual(await ensureInstalledSensorRowSnapshot(frameHost, '[data-action="inspectSensor"][data-sensor-id]', 1_000), {
    refreshed: true, response_type: 'snapshot'
  });
  assert.equal(refreshClicks, 1);
});

test('dashboard restart selects the persistent Pacify-X editor tab when it exists', async () => {
  let clicked = false;
  const dashboardTab = {
    async isVisible() { return true; },
    async click() { clicked = true; }
  };
  const workbench = {
    async bringToFront() {},
    keyboard: { async press(key) { assert.equal(key, 'Escape'); } },
    locator(selector, options) {
      assert.equal(selector, '[role="tab"]');
      assert.match('PX Control Plane', options.hasText);
      return { first: () => dashboardTab };
    }
  };
  assert.deepEqual(await reopenPacifyDashboardFromOwnedUi(workbench), { owner: 'existing-dashboard-tab', executed: true });
  assert.equal(clicked, true);
});

test('dashboard restart uses bounded exact-tab activation when a workbench overlay intercepts the pointer', async () => {
  let activated = false;
  const dashboardTab = {
    async isVisible() { return true; },
    async click() { throw new Error('modal overlay intercepted pointer'); },
    async evaluate(operation) { operation({ click() { activated = true; } }); }
  };
  const workbench = {
    async bringToFront() {},
    keyboard: { async press(key) { assert.equal(key, 'Escape'); } },
    locator(selector) {
      assert.equal(selector, '[role="tab"]');
      return { first: () => dashboardTab };
    }
  };
  assert.deepEqual(await reopenPacifyDashboardFromOwnedUi(workbench), { owner: 'existing-dashboard-tab', executed: true });
  assert.equal(activated, true);
});

test('dashboard restart falls back to the persistent Pacify-X status-bar command owner', async () => {
  let clicked = false;
  const status = {
    async waitFor(options) { assert.equal(options.state, 'visible'); },
    async getAttribute(name) { return name === 'aria-label' ? 'Open Pacify-X Control Plane' : ''; },
    async innerText() { return 'PX · ready'; },
    async click() { clicked = true; },
    async evaluate(operation) { operation({ click() { clicked = true; } }); }
  };
  const workbench = {
    async bringToFront() {},
    keyboard: { async press(key) { assert.equal(key, 'Escape'); } },
    locator(selector) {
      if (selector === '[role="tab"]') {
        return { first: () => ({ async isVisible() { return false; } }) };
      }
      assert.equal(selector, '.statusbar-item');
      return {
        filter(options) { assert.match('PX', options.hasText); return { first: () => status }; }
      };
    }
  };
  assert.deepEqual(await reopenPacifyDashboardFromOwnedUi(workbench), { owner: 'pacify-statusbar', executed: true });
  assert.equal(clicked, true);
});
