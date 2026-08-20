'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');
const { resolveBrowserLane } = require('./browser-lane');
const { buildSidebarProjection } = require('../src/sidebarProjection');
const { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL } = require('../src/sidebarMessages');

const browserLane = resolveBrowserLane();
const preview = pathToFileURL(path.join(__dirname, 'sidebar-preview.html')).href;
const visualEvidenceRoot = path.join(__dirname, '..', 'evidence', 'screenshots');
const NOW = Date.parse('2026-08-11T18:00:00Z');

function writeVisualManifest(browserVersion) {
  const files = fs.readdirSync(visualEvidenceRoot).filter(name => name.endsWith('.png')).sort().map(name => {
    const bytes = fs.readFileSync(path.join(visualEvidenceRoot, name));
    return { name, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  });
  fs.writeFileSync(path.join(visualEvidenceRoot, 'manifest.json'), `${JSON.stringify({ schema_version: 'px.ui-visual-evidence/1.0', generated_utc: new Date().toISOString(), browser: `${browserLane.name} ${browserVersion}`, platform: browserLane.platform, files }, null, 2)}\n`, 'utf8');
}

function projection() {
  const tasks = [
    { id: 'S02', title: 'Canonical projection', status: 'reconciled', weight: 2, depends_on: [] },
    { id: 'S03', title: 'Revision bridge', status: 'in_progress', weight: 1, depends_on: ['S02'], subtasks: [{ id: 'schema', title: 'Host schema', status: 'reconciled' }, { id: 'sync', title: 'Live sync', status: 'in_progress' }] },
    { id: 'S04', title: 'Message contracts', status: 'blocked', weight: 1, depends_on: ['S03'] }
  ];
  return buildSidebarProjection({
    connected: true, generatedAt: new Date(NOW).toISOString(), source: { version: '0.5.0' }, health: { authoritative: true, ready: true },
    attention: [{ id: 'review', severity: 'warning', title: 'Review contract evidence', detail: 'One gate remains.' }],
    providerActivity: [
      { providerId: 'openai', providerName: 'OpenAI API', providerClass: 'billable-api', connectionState: 'connected', activityState: 'active', billingEnabled: null, fallbackEnabled: true, fallbackActive: false, spendCurrent: 18, budgetLimit: 25, ratePerMinute: .4, currency: 'USD', currentTaskId: 'S03', currentTaskName: 'Revision bridge', telemetrySource: 'test-receipt', telemetryFreshAt: new Date(NOW - 10_000).toISOString() },
      { providerId: 'ollama', providerName: 'Ollama', providerClass: 'local', connectionState: 'connected', activityState: 'idle', billingEnabled: false, fallbackEnabled: false, fallbackActive: false, tokenTotal: 1000, telemetrySource: 'local', telemetryFreshAt: new Date(NOW - 10_000).toISOString() },
      { providerId: 'fallback', providerName: 'Enterprise fallback', providerClass: 'enterprise-budget', connectionState: 'connected', activityState: 'active', billingEnabled: true, fallbackEnabled: true, fallbackActive: true, spendCurrent: 9.7, budgetLimit: 10, currency: 'USD', telemetrySource: 'gateway', telemetryFreshAt: new Date(NOW - 10_000).toISOString() }
    ],
    coordinationData: { event_log_health: { status: 'healthy' }, events: [{ event_id: 'evt-1', operation: 'task-progress-recorded', timestamp: new Date(NOW - 30_000).toISOString(), result: { task_id: 'S03' } }], state: { revision: 142, updated_utc: new Date(NOW).toISOString(), active_plan: 'plan-live', plans: [{ id: 'plan-live', objective: 'Integration hardening', status: 'active', task_ids: tasks.map(item => item.id) }], tasks, claims: [{ id: 'claim-s03', task_id: 'S03', status: 'active', actor: { actor_id: 'codex', session_id: 'session-live' } }], sessions: [{ actor_id: 'codex', display_name: 'Codex', session_id: 'session-live', harness: 'VS Code', heartbeat_utc: new Date(NOW - 20_000).toISOString(), status: 'active' }], team_fabric: { work_rooms: [{ id: 'runtime-integration', name: 'Runtime Integration', status: 'running', updated_utc: new Date(NOW).toISOString() }] } } }
  }, { nowMs: NOW, expandedWaveIds: ['wave-1', 'wave-2'], expandedTaskIds: ['S03'], selectedProviderId: 'openai' });
}

async function send(page, value) { await page.evaluate(message => window.dispatchEvent(new MessageEvent('message', { data: message })), value); }
function snapshotMessage(value) {
  return { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot', capabilities: { renderAcknowledgement: true, assetProtocol: SIDEBAR_ASSET_PROTOCOL }, projection: value };
}

test('S05-S10 sidebar is keyboard-operable, revision-aware, and contained at 260/300/340px', { timeout: 60000 }, async t => {
  const browser = await chromium.launch({ executablePath: browserLane.executablePath, headless: true }); t.after(() => browser.close());
  const context = await browser.newContext({ viewport: { width: 300, height: 820 }, reducedMotion: 'reduce' });
  const page = await context.newPage(); const failures = [];
  page.on('console', message => { if (message.type() === 'error') failures.push(message.text()); }); page.on('pageerror', error => failures.push(error.message));
  await page.goto(preview); const p = projection();
  await send(page, { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot', projection: p });
  assert.equal(await page.evaluate(() => window.__sidebarMessages.filter(message => message.type === 'rendered').length), 0, 'legacy hosts without the negotiated capability must not receive render acknowledgements');
  await send(page, snapshotMessage(p));
  await page.locator('.control-plane').waitFor();
  assert.equal((await page.evaluate(() => window.__sidebarMessages.filter(message => message.type === 'rendered').at(-1))).assetProtocol, SIDEBAR_ASSET_PROTOCOL);
  assert.match(await page.locator('#execution').textContent(), /Integration hardening/);
  assert.match(await page.locator('#providers').textContent(), /BILLING STATE: UNKNOWN/);
  assert.match(await page.locator('#providers').textContent(), /BUDGET WARNING/);
  assert.equal(await page.locator('progress[aria-valuetext]').count() >= 2, true);
  assert.equal(await page.locator('[data-toggle-wave]').first().getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('[data-toggle-task="S03"]').getAttribute('aria-expanded'), 'true');
  await page.locator('.subtask-row').first().click();
  assert.deepEqual(await page.evaluate(() => window.__sidebarMessages.at(-1)), { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: 'S03.schema' });
  await page.locator('[data-toggle-task="S03"]').click();
  assert.equal((await page.evaluate(() => window.__sidebarMessages.at(-1))).type, 'toggleTask');
  assert.match(await page.locator('#punch').textContent(), /1 \/ 3/);
  await page.locator('[data-plan-punch="plan-live"]').click();
  assert.deepEqual(await page.evaluate(() => window.__sidebarMessages.at(-1)), { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openPlanFromPunch', planId: 'plan-live' });

  for (const width of [260, 300, 340]) {
    await page.setViewportSize({ width, height: 820 });
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth, providerBottom: document.getElementById('providers').getBoundingClientRect().bottom, sidebarBottom: document.getElementById('sidebar').getBoundingClientRect().bottom }));
    assert.ok(dimensions.document <= width + 1, `document overflow at ${width}: ${JSON.stringify(dimensions)}`);
    assert.ok(dimensions.body <= width + 1, `body overflow at ${width}: ${JSON.stringify(dimensions)}`);
    assert.ok(Math.abs(dimensions.providerBottom - dimensions.sidebarBottom) <= 1, `provider dock not pinned at ${width}`);
  }

  await page.locator('.control-plane').focus(); await page.keyboard.press('Enter');
  assert.equal((await page.evaluate(() => window.__sidebarMessages.at(-1))).type, 'openControlPlane');
  assert.equal(await page.locator('[data-action="provider-previous"]').getAttribute('aria-label'), 'Previous provider');
  assert.equal(await page.locator('[data-action="provider-next"]').getAttribute('aria-label'), 'Next provider');
  await page.locator('[data-action="provider-next"]').click();
  assert.equal((await page.evaluate(() => window.__sidebarMessages.at(-1))).type, 'providerNext');

  const second = structuredClone(p); second.revision = 143; second.generatedAt = new Date(NOW + 1_000).toISOString(); second.ui.selectedProviderId = 'ollama'; second.punch.complete = 2; second.punch.active = 0; second.punch.blocked = 1; await send(page, snapshotMessage(second));
  assert.match(await page.locator('#punch').textContent(), /2 \/ 3/);
  assert.match(await page.locator('#providers').textContent(), /LOCAL · NON-BILLABLE/);
  const third = structuredClone(p); third.generatedAt = new Date(NOW + 2_000).toISOString(); third.ui.selectedProviderId = 'fallback'; await send(page, snapshotMessage(third));
  assert.match(await page.locator('#providers').textContent(), /BILLABLE FALLBACK IN USE/);
  assert.match(await page.locator('#providers').textContent(), /BUDGET CRITICAL/);
  const providerGeometry = await page.locator('.provider-name').evaluate(element => {
    const strong = element.querySelector('strong').getBoundingClientRect();
    const small = element.querySelector('small').getBoundingClientRect();
    const parent = element.getBoundingClientRect();
    return { strongBottom: strong.bottom, smallTop: small.top, parentTop: parent.top, parentBottom: parent.bottom, strongTop: strong.top, smallBottom: small.bottom };
  });
  assert.ok(providerGeometry.strongBottom <= providerGeometry.smallTop + .5, `provider name and carousel count overlap: ${JSON.stringify(providerGeometry)}`);
  assert.ok(providerGeometry.strongTop >= providerGeometry.parentTop - .5 && providerGeometry.smallBottom <= providerGeometry.parentBottom + .5, `provider title escaped its control: ${JSON.stringify(providerGeometry)}`);
  const dockGeometry = await page.evaluate(() => {
    const scroll = document.getElementById('operational-scroll').getBoundingClientRect();
    const providers = document.getElementById('providers').getBoundingClientRect();
    return { scrollBottom: scroll.bottom, providerTop: providers.top };
  });
  assert.ok(dockGeometry.scrollBottom <= dockGeometry.providerTop + .5, `provider dock obscures the operational scroll viewport: ${JSON.stringify(dockGeometry)}`);

  await page.locator('.control-plane').evaluate(node => { node.dataset.preserved = 'yes'; });
  const agentsOnly = structuredClone(third); agentsOnly.generatedAt = new Date(NOW + 3_000).toISOString(); agentsOnly.agents[0].state = 'verifying'; await send(page, snapshotMessage(agentsOnly));
  assert.equal(await page.locator('.control-plane').getAttribute('data-preserved'), 'yes', 'unchanged header component must not rerender');
  const stale = structuredClone(p); stale.revision = 141; stale.generatedAt = new Date(NOW - 1_000).toISOString(); stale.execution.planName = 'STALE SHOULD NOT RENDER'; await send(page, snapshotMessage(stale));
  assert.doesNotMatch(await page.locator('#execution').textContent(), /STALE SHOULD NOT RENDER/);
  assert.equal(await page.locator('.control-plane span').evaluate(node => getComputedStyle(node).transitionDuration), '0s');
  await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
  assert.equal(await page.evaluate(() => matchMedia('(forced-colors: active)').matches), true);
  await page.locator('.control-plane').focus();
  assert.ok(await page.locator('.control-plane').evaluate(node => parseFloat(getComputedStyle(node).outlineWidth)) >= 2);
  fs.mkdirSync(visualEvidenceRoot, { recursive: true });
  const sidebarShot = await page.screenshot({ path: path.join(visualEvidenceRoot, 'sidebar-forced-colors-300px.png'), fullPage: true, animations: 'disabled' });
  assert.ok(sidebarShot.length > 10_000, 'sidebar visual evidence is unexpectedly empty');
  writeVisualManifest(browser.version());
  assert.deepEqual(failures, []);
});
