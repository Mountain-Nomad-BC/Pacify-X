'use strict';

// Exercise the complete typed action denominator against the current browser
// implementation in a synthetic, non-authoritative fixture.  This produces UI
// interaction evidence only; it never certifies host persistence or runtime
// effects and is intentionally not accepted by the live-host reconciler.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');
const { resolveBrowserLane } = require('../tests/browser-lane');
const { buildCurrentSourceControlManifest, canonicalSurfaceId } = require('./operational-ui-control-records');

const repositoryRoot = path.resolve(__dirname, '..', '..');
const inventoryPath = path.join(repositoryRoot, 'registry', 'operational_surface_inventory.json');
const preview = pathToFileURL(path.join(repositoryRoot, 'extension', 'tests', 'preview.html')).href;
const sidebarPreview = pathToFileURL(path.join(repositoryRoot, 'extension', 'tests', 'sidebar-preview.html')).href;
const output = path.resolve(process.argv[2] || path.join(repositoryRoot, 'evidence', 'contained-ui-action-walk', 'receipt.json'));
const routes = {
  dashboard: 'dashboard', projects: 'projects', agents: 'agents', 'agent-studio': 'agent-studio',
  'workflow-studio': 'workflow-studio', 'skill-studio': 'skill-studio', 'knowledge-graph': 'knowledgeGraph',
  'skills-tools': 'skillsTools', workflows: 'workflows', plugins: 'plugins', memory: 'memory', activity: 'activity',
  diagnostics: 'diagnostics', assurance: 'assurance', 'studio-lifecycle': 'studio-lifecycle', settings: 'settings',
  'knowledge-core': 'knowledgeCore', 'runtime-core': 'runtimeCore'
};

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
const digest = value => crypto.createHash('sha256').update(canonical(value)).digest('hex');

function actionIdentity(control) {
  const parts = String(control.label).split('.');
  if (parts[0] === 'dynamicRepair') return { action: parts[1], variants: parts.slice(2) };
  return { action: parts[0], variants: parts.slice(1) };
}

function matchesVariant(dataset, variants) {
  const values = new Set(Object.values(dataset).map(String));
  return variants.every(variant => variant === 'row'
    ? Object.keys(dataset).some(key => /id|index|row|key/i.test(key))
    : values.has(variant));
}

async function settle(page, sidebar) {
  await page.locator(sidebar ? '#sidebar' : 'main h1').first().waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(180);
}

async function prepareState(page, control) {
  const surface = canonicalSurfaceId(control.surface_id);
  if (surface === 'sidebar') {
    await page.goto(sidebarPreview);
    await settle(page, true);
    return;
  }
  const route = routes[surface] || 'dashboard';
  const { action } = actionIdentity(control);
  const modal = surface === 'dashboard-control-plane' && ['cleanupRecycle', 'cleanupPermanent', 'cleanupSelectAll', 'refreshCleanup'].includes(action)
    ? '&modal=cleanup'
    : surface === 'dashboard-control-plane' && !['navigate', 'toggleAdvanced', 'commandCenter', 'openSettings', 'refresh'].includes(action)
      ? '&modal=controls' : '';
  await page.goto(`${preview}?surface=${route}${modal}`);
  await settle(page, false);
  if (['agent-studio', 'workflow-studio', 'skill-studio'].includes(surface)) {
    const kind = surface.split('-')[0];
    const studioAction = page.locator(`[data-action="openStudioDraft"][data-kind="${kind}"]`).first();
    if (await studioAction.count()) {
      await studioAction.click();
      await page.locator('.studio-modal').waitFor({ state: 'visible', timeout: 5_000 });
      await page.waitForTimeout(100);
    }
  }
}

async function resolveCandidates(page, control) {
  const surface = canonicalSurfaceId(control.surface_id);
  const { action, variants } = actionIdentity(control);
  if (action === 'navigate') {
    const target = variants[0];
    return page.locator(`[data-surface="${target}"]`);
  }
  let name = action;
  if (surface === 'sidebar') name = String(control.label);
  const candidates = page.locator(`[data-action="${name}"]`);
  const count = await candidates.count();
  const matching = [];
  for (let index = 0; index < count; index += 1) {
    const item = candidates.nth(index);
    const dataset = await item.evaluate(element => ({ ...element.dataset }));
    if (matchesVariant(dataset, variants)) matching.push(index);
  }
  return { candidates, matching, count };
}

async function examine(page, control) {
  const errors = [];
  const onPageError = error => errors.push(`page:${String(error?.message || error).slice(0, 500)}`);
  const onConsole = message => { if (message.type() === 'error') errors.push(`console:${message.text().slice(0, 500)}`); };
  page.on('pageerror', onPageError);
  page.on('console', onConsole);
  try {
    await prepareState(page, control);
    const before = await page.evaluate(() => ({
      text: document.body.innerText.slice(0, 40_000),
      messages: Array.isArray(window.__PX_POSTED_MESSAGES__) ? window.__PX_POSTED_MESSAGES__.length : null,
      dialogs: document.querySelectorAll('[role="dialog"],.studio-modal').length,
      active: document.activeElement?.id || document.activeElement?.getAttribute?.('data-action') || null
    }));
    const resolved = await resolveCandidates(page, control);
    let locator;
    let matchCount;
    if (resolved && typeof resolved.count === 'function') {
      matchCount = await resolved.count();
      locator = resolved.first();
    } else {
      matchCount = resolved.matching.length;
      locator = matchCount ? resolved.candidates.nth(resolved.matching[0]) : null;
    }
    if (!locator || matchCount < 1) return { status: 'not_rendered', match_count: matchCount || 0, errors };
    const visible = await locator.isVisible().catch(() => false);
    const enabled = await locator.isEnabled().catch(() => false);
    if (!visible) return { status: 'not_visible', match_count: matchCount, errors };
    if (!enabled) return { status: 'validation_blocked', match_count: matchCount, visible, enabled, errors };
    const dataset = await locator.evaluate(element => ({ ...element.dataset }));
    await locator.click({ timeout: 5_000 });
    await page.waitForTimeout(140);
    const after = await page.evaluate(() => ({
      text: document.body.innerText.slice(0, 40_000),
      messages: Array.isArray(window.__PX_POSTED_MESSAGES__) ? window.__PX_POSTED_MESSAGES__.length : null,
      dialogs: document.querySelectorAll('[role="dialog"],.studio-modal').length,
      active: document.activeElement?.id || document.activeElement?.getAttribute?.('data-action') || null
    }));
    return {
      status: errors.length ? 'interaction_error' : 'attempted', match_count: matchCount, visible, enabled, dataset,
      before_state_sha256: digest(before), after_state_sha256: digest(after), changed: digest(before) !== digest(after),
      message_count_before: before.messages, message_count_after: after.messages, errors
    };
  } catch (error) {
    errors.push(`walker:${String(error?.message || error).slice(0, 1000)}`);
    return { status: 'interaction_error', match_count: 0, errors };
  } finally {
    page.off('pageerror', onPageError);
    page.off('console', onConsole);
  }
}

async function main() {
  const manifest = buildCurrentSourceControlManifest(inventoryPath);
  const controls = manifest.controls.filter(control => control.kind === 'action');
  const lane = resolveBrowserLane();
  const browser = await chromium.launch({ executablePath: lane.executablePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const records = [];
  try {
    for (const control of controls) records.push({
      control_id: control.control_id, surface_id: control.surface_id, label: control.label,
      contract: control.outbound_contract, ...(await examine(page, control))
    });
  } finally {
    await browser.close();
  }
  const counts = {};
  for (const record of records) counts[record.status] = (counts[record.status] || 0) + 1;
  const receipt = {
    schema_version: 'px.contained-ui-action-walk/1.0',
    authority: 'Synthetic current-source browser fixture; UI interaction evidence only; never host/runtime/persistence certification.',
    observed_at: new Date().toISOString(),
    source: { manifest_sha256: manifest.manifest_sha256, inventory_id: manifest.source_inventory.inventory_id },
    browser: { lane: lane.name, platform: lane.platform },
    action_control_count: controls.length,
    aggregates: counts,
    operationally_complete: false,
    records
  };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ output, action_control_count: controls.length, aggregates: counts }, null, 2)}\n`);
  if (records.some(record => record.status === 'interaction_error')) process.exitCode = 1;
}

if (require.main === module) {
  main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
}

module.exports = { actionIdentity, matchesVariant };
