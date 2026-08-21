'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { build, serialized } = require('../scripts/build-ui-action-inventory');
const {
  buildCurrentSourceControlManifest,
  buildPerControlRecords,
  loadOperationalSurfaceInventory
} = require('../scripts/operational-ui-control-records');
const { HEALTH_DIMENSIONS, createHealthState, healthLabel } = require('../src/healthState');

const root = path.resolve(__dirname, '..');

test('H05 every rendered action has one effect/authority/schema/outcome contract and generated artifact is current', () => {
  const report = build();
  const checkedIn = fs.readFileSync(path.join(root, 'resources', 'ui', 'action-inventory.json'), 'utf8');
  assert.equal(checkedIn, serialized());
  assert.equal(report.action_count, report.actions.length);
  assert.ok(report.action_count >= 70);
  for (const item of report.actions) {
    assert.ok(item.authority, item.action);
    assert.ok(item.effect, item.action);
    assert.ok(item.state_transition, item.action);
    assert.ok(item.acknowledgement, item.action);
    assert.ok(item.rendered_in.length, item.action);
    if (item.mode === 'host') {
      assert.ok(item.inbound_schema?.type, item.action);
      assert.ok(item.receipt, item.action);
    } else {
      assert.equal(item.mode, 'ui-only');
      assert.equal(item.effect, 'none-outside-webview');
      assert.equal(item.inbound_schema, null);
    }
  }
});

test('H05 generated host mappings resolve to admitted schema and host authority switches', () => {
  const report = build();
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  for (const item of report.actions.filter(row => row.mode === 'host')) {
    const type = item.inbound_schema.type;
    assert.match(extension, new RegExp(`case ['\"]${type}['\"]|case ['\"][^'\"]+['\"]:\\s*\\n\\s*case ['\"]${type}['\"]`), `${item.action}:${type}`);
  }
});

test('H06 source health contract rejects false promotions and labels only strongest evidenced state', () => {
  assert.deepEqual(HEALTH_DIMENSIONS, ['configured', 'detected', 'connected', 'authoritative', 'ready']);
  assert.throws(() => createHealthState({ ready: true }), /ready-requires-authoritative/);
  assert.throws(() => createHealthState({ connected: true }), /connected-requires-detected/);
  const authoritative = createHealthState({ configured: true, detected: true, connected: true, authoritative: true, ready: false });
  assert.equal(healthLabel(authoritative), 'AUTHORITATIVE');
  const contract = JSON.parse(fs.readFileSync(path.join(root, 'resources', 'ui', 'health-state-contract.json'), 'utf8'));
  assert.deepEqual(contract.display_order, HEALTH_DIMENSIONS);
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  assert.doesNotMatch(extension, /currentSnapshot\.connected[^\n]+PX · ready/);
  assert.match(extension, /currentSnapshot\.health = createHealthState/);
  assert.match(extension, /healthLabel\(currentSnapshot\.health\)/);
});

test('H05 actions are visibly handled and governed previews cannot fall through to false success', () => {
  const dashboard = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  for (const item of build().actions) {
    const literalHandler = dashboard.includes(`action === '${item.action}'`);
    const messageMapHandler = new RegExp(`${item.action}: ['\"]`).test(dashboard);
    assert.equal(literalHandler || messageMapHandler, true, item.action);
  }
  assert.match(dashboard, /if \(action === 'openEngineRoot'\)[\s\S]*NO CONFIGURED TARGET/);
});

test('operational ledger actions keep local editor state separate from exact host queries', () => {
  const actions = Object.fromEntries(build().actions.map(item => [item.action, item]));
  assert.equal(actions.workflowAddBinding.mode, 'ui-only');
  for (const action of ['agentPortConnect', 'agentCancelConnection', 'agentRemoveEdge']) {
    assert.equal(actions[action].mode, 'ui-only');
    assert.equal(actions[action].authority, 'webview presentation state');
    assert.equal(actions[action].effect, 'none-outside-webview');
    assert.equal(actions[action].inbound_schema, null);
    assert.equal(actions[action].state_transition, 'editor-state');
  }
  assert.equal(actions.knowledgeRollback.mode, 'ui-only');
  assert.equal(actions.inspectPunchCard.inbound_schema.type, 'operationalCardQuery');
  assert.equal(actions.inspectOperationalInventory.inbound_schema.type, 'operationalInventoryQuery');
  assert.equal(actions.queryOperationalCards.inbound_schema.type, 'operationalCardsQuery');
});

test('current-source control manifest binds the canonical denominator, sources, locators, handlers, and contracts', () => {
  const inventoryPath = path.join(root, '..', 'registry', 'operational_surface_inventory.json');
  const inventory = JSON.parse(fs.readFileSync(inventoryPath, 'utf8'));
  const manifest = buildCurrentSourceControlManifest(inventoryPath);
  const expectedControls = inventory.surfaces.reduce((total, surface) => total + surface.controls.length, 0);

  assert.equal(manifest.schema_version, 'px.current-source-control-manifest/1.0');
  assert.equal(manifest.source_inventory.path, 'registry/operational_surface_inventory.json');
  assert.equal(manifest.source_inventory.inventory_id, inventory.inventory_id);
  assert.equal(manifest.surfaces.length, inventory.surfaces.length);
  assert.equal(manifest.controls.length, expectedControls);
  assert.equal(new Set(manifest.controls.map(control => control.control_id)).size, expectedControls);
  assert.match(manifest.manifest_sha256, /^[a-f0-9]{64}$/);
  for (const control of manifest.controls) {
    assert.ok(control.route.surface_id, control.control_id);
    assert.ok(control.locator.type, control.control_id);
    assert.ok(control.outbound_contract.authority, control.control_id);
    assert.ok(control.outbound_contract.effect, control.control_id);
    assert.ok(control.handler.backend, control.control_id);
    assert.ok(control.source_identity.refs.length, control.control_id);
    assert.ok(control.source_identity.files.length, control.control_id);
    for (const source of control.source_identity.files) assert.match(source.source_sha256, /^[a-f0-9]{64}$/);
  }
});

test('typed inventory includes every current dashboard navigation surface', () => {
  const inventory = JSON.parse(fs.readFileSync(path.join(root, '..', 'registry', 'operational_surface_inventory.json'), 'utf8'));
  const controller = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  const navigationSurfaces = ['visibleSurfaces', 'advancedSurfaces'].flatMap(declaration => {
    const match = controller.match(new RegExp(`const\\s+${declaration}\\s*=\\s*\\[([\\s\\S]*?)\\];`));
    assert.ok(match, declaration);
    return [...match[1].matchAll(/\[\s*['"]([^'"]+)['"]\s*,/g)].map(item => item[1]);
  });
  const dashboard = inventory.surfaces.find(surface => surface.surface_id === 'dashboard-control-plane');
  assert.ok(dashboard);
  const registered = new Set(
    dashboard.controls
      .filter(control => control.kind === 'action' && control.label.startsWith('navigate.'))
      .map(control => control.label.slice('navigate.'.length))
  );
  assert.deepEqual([...registered].sort(), [...navigationSurfaces].sort());
  assert.equal(inventory.dashboard_navigation_surface_count, navigationSurfaces.length);
  assert.match(inventory.dashboard_controller_sha256, /^[a-f0-9]{64}$/);
});

test('current-source control manifest rejects a substitute inventory path', () => {
  assert.throws(
    () => buildCurrentSourceControlManifest(path.join(root, 'package.json')),
    /canonical operational surface inventory/
  );
});

test('operational action resolution treats repeated classes and camel-case row identities as exact', () => {
  const inventoryPath = path.join(root, '..', 'registry', 'operational_surface_inventory.json');
  const inventory = loadOperationalSurfaceInventory(inventoryPath);
  const chains = buildPerControlRecords({
    inventory,
    results: [{
      surface: 'activity',
      visible_actions: [
        { action: 'inspectMetric', disabled: false, dataset: { metricLabel: 'FIRST' } },
        { action: 'inspectMetric', disabled: false, dataset: { metricLabel: 'SECOND' } },
        { action: 'inspectActivityEvent', disabled: false, dataset: { eventId: 'event:one' } },
        { action: 'inspectActivityEvent', disabled: false, dataset: { eventId: 'event:two' } }
      ]
    }]
  });
  const byId = Object.fromEntries(chains.controls.map(control => [control.control_id, control]));
  assert.equal(byId['pxui.activity.action.inspectMetric'].resolver.status, 'exact');
  assert.equal(byId['pxui.activity.action.inspectMetric'].resolver.match_count, 2);
  assert.equal(byId['pxui.activity.action.inspectActivityEvent.row'].resolver.status, 'exact');
  assert.equal(byId['pxui.activity.action.inspectActivityEvent.row'].resolver.match_count, 2);
});
