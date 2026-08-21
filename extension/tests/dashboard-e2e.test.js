'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');
const { resolveBrowserLane } = require('./browser-lane');

const browserLane = resolveBrowserLane();
const preview = pathToFileURL(path.join(__dirname, 'preview.html')).href;
const visualEvidenceRoot = path.join(__dirname, '..', 'evidence', 'screenshots');

async function settled(page) {
  await page.locator('main h1').waitFor({ state: 'visible' });
  await page.waitForTimeout(180);
}

async function noHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(dimensions.document <= dimensions.viewport + 1, `${label} document overflow: ${JSON.stringify(dimensions)}`);
  assert.ok(dimensions.body <= dimensions.viewport + 1, `${label} body overflow: ${JSON.stringify(dimensions)}`);
}

async function assertContained(page, childSelector, parentSelector, label) {
  const boxes = await page.evaluate(({ childSelector, parentSelector }) => {
    const child = document.querySelector(childSelector); const parent = document.querySelector(parentSelector);
    if (!child || !parent) return null;
    const c = child.getBoundingClientRect(); const p = parent.getBoundingClientRect();
    return { child: { left: c.left, top: c.top, right: c.right, bottom: c.bottom, width: c.width, height: c.height }, parent: { left: p.left, top: p.top, right: p.right, bottom: p.bottom, width: p.width, height: p.height } };
  }, { childSelector, parentSelector });
  assert.ok(boxes, `${label}: selectors resolve`);
  assert.ok(boxes.child.left >= boxes.parent.left - 1, `${label}: left edge escaped ${JSON.stringify(boxes)}`);
  assert.ok(boxes.child.top >= boxes.parent.top - 1, `${label}: top edge escaped ${JSON.stringify(boxes)}`);
  assert.ok(boxes.child.right <= boxes.parent.right + 1, `${label}: right edge escaped ${JSON.stringify(boxes)}`);
  assert.ok(boxes.child.bottom <= boxes.parent.bottom + 1, `${label}: bottom edge escaped ${JSON.stringify(boxes)}`);
  return boxes;
}

async function assertNoIntersection(page, firstSelector, secondSelector, label) {
  const result = await page.evaluate(({ firstSelector, secondSelector }) => {
    const first = document.querySelector(firstSelector); const second = document.querySelector(secondSelector);
    if (!first || !second) return null;
    const a = first.getBoundingClientRect(); const b = second.getBoundingClientRect();
    return { intersects: a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top, a: { left: a.left, top: a.top, right: a.right, bottom: a.bottom }, b: { left: b.left, top: b.top, right: b.right, bottom: b.bottom } };
  }, { firstSelector, secondSelector });
  assert.ok(result, `${label}: selectors resolve`);
  assert.equal(result.intersects, false, `${label}: elements overlap ${JSON.stringify(result)}`);
}

async function assertHeaderSeparation(page, label) {
  const geometry = await page.locator('.cockpit-header').evaluate(header => {
    const visible = element => getComputedStyle(element).display !== 'none' && element.getBoundingClientRect().width > 0;
    const rect = element => { const box = element.getBoundingClientRect(); return { name: element.className, left: box.left, right: box.right, width: box.width }; };
    return {
      cells: [...header.children].filter(visible).map(rect).sort((a, b) => a.left - b.left),
      buttons: [...header.querySelectorAll('.cockpit-actions button')].filter(visible).map(rect).sort((a, b) => a.left - b.left)
    };
  });
  for (const collection of [geometry.cells, geometry.buttons]) {
    for (let index = 1; index < collection.length; index += 1) {
      assert.ok(collection[index - 1].right <= collection[index].left + .5, `${label}: header controls overlap ${JSON.stringify(collection)}`);
    }
  }
  for (const button of geometry.buttons) assert.ok(button.width >= 37, `${label}: action target collapsed ${JSON.stringify(button)}`);
}

function writeVisualManifest(browserVersion) {
  const files = fs.readdirSync(visualEvidenceRoot).filter(name => name.endsWith('.png')).sort().map(name => {
    const bytes = fs.readFileSync(path.join(visualEvidenceRoot, name));
    return { name, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  });
  fs.writeFileSync(path.join(visualEvidenceRoot, 'manifest.json'), `${JSON.stringify({ schema_version: 'px.ui-visual-evidence/1.0', generated_utc: new Date().toISOString(), browser: `${browserLane.name} ${browserVersion}`, platform: browserLane.platform, files }, null, 2)}\n`, 'utf8');
}

test('Playwright drives every dashboard route and high-risk interaction without console or layout errors', { timeout: 120000 }, async t => {
  fs.mkdirSync(visualEvidenceRoot, { recursive: true });
  const browser = await chromium.launch({ executablePath: browserLane.executablePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  t.after(async () => { await browser.close(); });
  const page = await context.newPage();
  const failures = [];
  page.on('console', message => { if (message.type() === 'error') failures.push(`console: ${message.text()}`); });
  page.on('pageerror', error => failures.push(`page: ${error.message}`));
  page.on('requestfailed', request => failures.push(`request: ${request.url()} ${request.failure()?.errorText || ''}`));
  await page.goto(`${preview}?surface=dashboard`); await settled(page);
  assert.equal(await page.locator('#app').getAttribute('aria-live'), null);
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'deepLink', route: '/control-plane/knowledge-graph' } })));
  await page.locator('main h1').filter({ hasText: 'Knowledge Graph' }).waitFor({ state: 'visible' });
  await page.locator('.graph-node.actual').first().waitFor({ state: 'visible' });
  await page.waitForFunction(() => window.__PX_POSTED_MESSAGES__?.some(message => message.type === 'graphRendered' && message.nodeCount > 0 && message.edgeCount > 0 && message.visibleNodeCount > 0 && message.canvasWidth > 0 && message.canvasHeight > 0));

  const routes = [
    ['dashboard', 'Dashboard'], ['projects', 'Projects'], ['agents', 'Agents'], ['agent-studio', 'Agent Studio'],
    ['workflow-studio', 'Workflow Studio'], ['skill-studio', 'Skill Studio'], ['studio-lifecycle', 'Studio Lifecycle'], ['knowledgeGraph', 'Knowledge Graph'],
    ['skillsTools', 'Skills & Tools'], ['workflows', 'Workflows'], ['plugins', 'Plugin Manager'], ['memory', 'Memory'],
    ['activity', 'Activity'], ['diagnostics', 'Diagnostics'], ['assurance', 'Assurance'], ['settings', 'Settings'], ['knowledgeCore', 'Knowledge Core'], ['runtimeCore', 'Runtime Core']
  ];
  for (const [surface, heading] of routes) {
    await page.goto(`${preview}?surface=${surface}`); await settled(page);
    assert.equal(await page.locator('main h1').textContent(), heading);
    await noHorizontalOverflow(page, surface);
    const shot = await page.screenshot({ path: path.join(visualEvidenceRoot, `surface-${surface}-1440.png`), animations: 'disabled' });
    assert.ok(shot.length > 10_000, `${surface} visual evidence is unexpectedly empty`);
  }

  await page.goto(`${preview}?surface=dashboard`); await settled(page);
  assert.equal(await page.locator('.primary-nav .nav-item').count(), 16);
  for (const [surface, title, editableSelector] of [
    ['agent-studio', 'Agent Studio', '[data-agent-root-field="instructions"]'],
    ['workflow-studio', 'Workflow Studio', '[data-workflow-editor-canvas]'],
    ['skill-studio', 'Skill Studio', '#studio-skill-file']
  ]) {
    await page.locator(`[data-surface="${surface}"]`).click();
    await page.locator('[role="dialog"]').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.control-modal h2').textContent(), title);
    assert.equal(await page.locator(editableSelector).isVisible(), true, `${surface} navigation must open its authoring workspace, not stop at the catalog`);
    assert.equal(await page.locator('[data-action="submitStudioDraft"]').isVisible(), true);
    await page.keyboard.press('Escape');
  }
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'deepLink', route: '/control-plane/skill-studio' } })));
  await page.locator('[role="dialog"]').waitFor({ state: 'visible' });
  assert.equal(await page.locator('main h1').textContent(), 'Skill Studio');
  assert.equal(await page.locator('#studio-skill-file').isVisible(), true);
  await page.keyboard.press('Escape');
  for (const [surface, rowKind, studioKind, editorSelector] of [
    ['agents', 'agents', 'agent', '.agent-builder-layout'],
    ['workflows', 'workflows', 'workflow', '[data-control-id="workflow-canvas"]']
  ]) {
    await page.goto(`${preview}?surface=${surface}`); await settled(page);
    await page.locator(`.catalog-row[data-kind="${rowKind}"]`).nth(1).click();
    await page.locator(`[data-action="importCatalogDefinition"][data-kind="${studioKind}"]`).click();
    await page.locator(editorSelector).waitFor({ state: 'visible' });
    assert.match(await page.locator('.studio-revision-baseline').textContent(), /IMPORTED INTO AN INDEPENDENT STUDIO CANDIDATE/);
    assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isVisible(), true);
    await page.keyboard.press('Escape');
  }
  await page.goto(`${preview}?surface=dashboard`); await settled(page);
  await page.locator('[data-action="inspectMetric"]').first().click();
  await page.locator('[role="dialog"]').waitFor();
  await page.locator('[data-tab="machine"]').click();
  assert.equal(await page.locator('#info-machine').isVisible(), true);
  await page.keyboard.press('Escape'); assert.equal(await page.locator('[role="dialog"]').count(), 0);
  await page.locator('[data-action="commandCenter"]').click();
  await page.locator('[data-action="cleanupManager"]').click();
  await page.locator('.cleanup-row').first().waitFor({ state: 'visible' });
  assert.equal(await page.locator('.cleanup-row').count(), 3);
  await assertContained(page, '.cleanup-summary', '.modal-body', 'cleanup-summary');
  await assertContained(page, '.cleanup-toolbar', '.modal-body', 'cleanup-toolbar');
  assert.equal(await page.locator('[data-action="cleanupPermanent"]').isDisabled(), true);
  await page.locator('[data-action="cleanupSelectAll"]').click();
  assert.equal(await page.locator('[data-action="cleanupPermanent"]').isEnabled(), true);
  await page.keyboard.press('Escape');

  await page.goto(`${preview}?surface=agents`); await settled(page);
  await page.locator('[data-action="setupStudio"]').click();
  const setupRequest = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'setupStudio'));
  assert.match(setupRequest.requestId, /^[a-zA-Z0-9._:-]+$/);
  await page.evaluate(requestId => window.dispatchEvent(new MessageEvent('message', { data: {
    type: 'studioSetupResult', requestId,
    result: {
      schema_version: 'px.studio-setup-result/1.0', ready: true,
      agent: { identity: 'agent:pacify-x-starter', version: '1.0.0', decision: 'admitted', run_id: 'run:agent-starter', run_outcome: 'succeeded' },
      workflow: { identity: 'workflow:pacify-x-starter', version: '1.0.0', decision: 'admitted', run_id: 'run:workflow-starter', run_state: 'succeeded' },
      completed_steps: ['agent_create', 'agent_test', 'agent_authority', 'agent_admit', 'agent_run', 'workflow_create', 'workflow_authority', 'workflow_validate', 'workflow_dry_run', 'workflow_run']
    }
  } })), setupRequest.requestId);
  await page.locator('[role="dialog"]').filter({ hasText: 'operational' }).waitFor({ state: 'visible' });
  assert.match(await page.locator('[role="dialog"]').textContent(), /admitted.*bounded runs succeeded/i);
  await page.keyboard.press('Escape');
  assert.match(await page.evaluate(() => window.__PX_PREVIEW_ALLOCATION_FIXTURE__?.authority || ''), /synthetic preview fixture; non-authoritative; UI interaction evidence only/);
  const utcValidation = await page.evaluate(() => {
    const editors = window.PXDashboard.require('studioEditors');
    return {
      canonical: editors.validCanonicalUtc('2026-08-17T00:00:00.000Z'),
      noFraction: editors.validCanonicalUtc('2026-08-17T00:00:00Z'),
      yearZero: editors.validCanonicalUtc('0000-01-01T00:00:00.000Z'),
      overflow: editors.validCanonicalUtc('2026-02-31T00:00:00.000Z'),
      offset: editors.validCanonicalUtc('2026-08-17T00:00:00+00:00')
    };
  });
  assert.deepEqual(utcValidation, { canonical: true, noFraction: true, yearZero: false, overflow: false, offset: false });
  await page.locator('[data-action="inspectCatalogItem"]').first().click();
  assert.equal(await page.locator('.agent-model').isVisible(), true);
  // UI interaction evidence only: the preview is synthetic and does not certify backend persistence or admission.
  const cancelledAgentAllocation = await page.evaluate(() => {
    document.querySelector('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadStudioRevisionEditor' && message.kind === 'agent');
    const loading = document.querySelector('.cleanup-loading')?.textContent || '';
    document.querySelector('.modal-backdrop').click();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioRevisionEditorResult', requestId: request.requestId, kind: 'agent', catalogKind: request.catalogKind, recordId: request.recordId, selection: {}, allocation: {}, allocationProof: 'version-allocation:cancelled-preview-proof' } }));
    return { request, loading };
  });
  assert.match(cancelledAgentAllocation.request.requestId, /^[a-zA-Z0-9._:-]{1,200}$/);
  assert.match(cancelledAgentAllocation.loading, /Re-reading and authenticating the complete physical revision/);
  await page.waitForTimeout(35);
  assert.equal(await page.locator('.agent-builder-layout').count(), 0, 'backdrop cancellation must reject a late allocation result');
  await page.locator('.catalog-row[data-kind="agents"]').first().click();
  const substitutedAgentAllocation = await page.evaluate(() => {
    document.querySelector('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadStudioRevisionEditor' && message.kind === 'agent');
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'studioOperation', suboperation: 'next-version', requestId: request.requestId, kind: request.kind, error: 'Synthetic wrong-family allocation failure.' } }));
    const wrongFamilyIgnored = /Re-reading and authenticating the complete physical revision/.test(document.querySelector('.cleanup-loading')?.textContent || '');
    const record = {
      agent_id: 'agent:preview-catalog', version: '1.0.9', project_id: 'project:preview', owner: 'human:owner',
      harness_id: 'harness:px', instructions: 'Substituted source revision.', capability_binding_ids: ['binding:preview-agent'],
      effect_grant_ids: ['grant:preview-agent'], required_tests: ['identity', 'sandbox'], grants: [], bindings: [], lifecycle: 'admitted',
      revision_sha256: '4'.repeat(64), source_content_sha256: '5'.repeat(64)
    };
    const selection = { kind: 'agent', catalog_kind: request.catalogKind, record_id: request.recordId, identity: record.agent_id, source_version: record.version, source_revision_sha256: record.revision_sha256, source_content_sha256: record.source_content_sha256, record };
    const allocation = { schema_version: 'px.studio-version-allocation/1.0', kind: 'agent', identity: record.agent_id, source_version: record.version, source_scope: 'studio-physical', source_revision_sha256: record.revision_sha256, source_content_sha256: record.source_content_sha256, candidate_version: '1.0.10', occupied_versions_sha256: '8'.repeat(64), observed_utc: '2026-08-16T00:00:00Z' };
    const expectedAllocation = { ...allocation, identity: request.identity, source_version: request.source_version, source_revision_sha256: request.source_revision_sha256, source_content_sha256: request.source_content_sha256, candidate_version: '1.0.1' };
    const malformedProof = 'version-allocation:malformed-active-proof';
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioRevisionEditorResult', requestId: request.requestId, kind: request.kind, catalogKind: request.catalogKind, recordId: request.recordId, selection: {}, allocation: { ...expectedAllocation, extra: true }, allocationProof: malformedProof } }));
    const crossKindProof = 'version-allocation:cross-kind-active-proof';
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioRevisionEditorResult', requestId: request.requestId, kind: request.kind, catalogKind: request.catalogKind, recordId: request.recordId, selection: {}, allocation: { ...expectedAllocation, kind: 'workflow' }, allocationProof: crossKindProof } }));
    const proof = 'version-allocation:substituted-preview-proof';
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioRevisionEditorResult', requestId: request.requestId, kind: 'agent', catalogKind: request.catalogKind, recordId: request.recordId, selection, allocation, allocationProof: proof } }));
    return {
      wrongFamilyIgnored,
      accepted: Boolean(document.querySelector('.agent-builder-layout')),
      released: [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'releaseStudioTrust' && message.requestId === request.requestId && message.proof === proof),
      malformedReleased: [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'releaseStudioTrust' && message.requestId === request.requestId && message.proof === malformedProof),
      crossKindReleased: [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'releaseStudioTrust' && message.requestId === request.requestId && message.proof === crossKindProof)
    };
  });
  assert.equal(substitutedAgentAllocation.wrongFamilyIgnored, true, 'a same-ID next-version failure must not consume a physical revision load');
  assert.equal(substitutedAgentAllocation.accepted, false, 'an internally consistent substituted revision must not replace the selected catalog revision');
  assert.equal(substitutedAgentAllocation.released, true, 'a rejected substituted allocation proof must be released');
  assert.equal(substitutedAgentAllocation.malformedReleased, true, 'an active malformed allocation proof must be released');
  assert.equal(substitutedAgentAllocation.crossKindReleased, true, 'an active cross-kind allocation proof must be released');
  await page.locator('.agent-builder-layout').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#studio-identity').getAttribute('readonly'), '');
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), '');
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.1');
  assert.equal(await page.locator('.studio-revision-baseline').isVisible(), true);
  await page.locator('[data-control-id="studio-save-candidate"]').click();
  const predecessorAgentSave = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'createStudioDraft' && message.kind === 'agent'));
  assert.equal(predecessorAgentSave.payload.agent_id, 'agent:preview-catalog');
  assert.equal(predecessorAgentSave.payload.version, '1.0.1');
  assert.equal(predecessorAgentSave.payload.version_allocation.identity, 'agent:preview-catalog');
  assert.equal(predecessorAgentSave.payload.version_allocation.source_scope, 'studio-physical');
  assert.equal(predecessorAgentSave.payload.version_allocation.candidate_version, '1.0.1');
  assert.match(predecessorAgentSave.payload.version_allocation_proof, /^version-allocation:/);
  assert.match(await page.locator('[data-action="closeModal"]').last().textContent(), /Detach.*save may continue/);
  await page.locator('[data-action="closeModal"]').first().click();
  assert.equal(await page.evaluate(proof => [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'releaseStudioTrust' && message.proof === proof), predecessorAgentSave.payload.version_allocation_proof), false, 'an in-flight save owns its consumed allocation proof');
  await page.locator('[data-action="openStudioDraft"][data-kind="agent"]').click();
  await page.locator('[data-agent-root-field="instructions"]').fill('Newer local agent draft survives detached predecessor result.');
  await page.evaluate(request => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftResult', requestId: request.requestId, kind: request.kind, result: { created: true } } })), predecessorAgentSave);
  assert.equal(await page.locator('[data-agent-root-field="instructions"]').inputValue(), 'Newer local agent draft survives detached predecessor result.', 'a detached older save result must not mutate the newer same-kind editor');
  await page.keyboard.press('Escape');
  await page.locator('[data-action="openStudioDraft"][data-kind="agent"]').click();
  assert.match(await page.locator('#modal-root').textContent(), /Recover unsaved Studio draft/);
  await page.locator('[data-action="resumeWorkingStudioDraft"][data-kind="agent"]').click();
  assert.equal(await page.locator('.agent-builder-layout').isVisible(), true);
  assert.equal(await page.locator('[data-agent-root-field="instructions"]').inputValue(), 'Newer local agent draft survives detached predecessor result.');
  assert.match(await page.locator('.agent-builder-domain').textContent(), /PX-STANDARD BUILDER/);
  await page.locator('#studio-version').fill('1.0.0-RC.1');
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isDisabled(), true, 'browser and host must reject non-canonical version casing');
  await page.locator('#studio-version').fill('1.0.0');
  assert.equal(await page.locator('.agent-graph-node').count(), 9);
  assert.match(await page.locator('.agent-graph-state').textContent(), /WORKING.*PYTHON COMPILE REQUIRED/);
  assert.equal(await page.locator('[data-agent-editor-canvas]').getAttribute('role'), 'region');
  await page.locator('[data-agent-node-id="agent-node:behavior"]').click();
  assert.equal(await page.locator('[data-agent-inspector] [data-agent-root-field="instructions"]').isVisible(), true);
  await page.locator('[data-action="agentZoom"][data-delta="0.1"]').click();
  assert.match(await page.locator('.agent-canvas-toolbar output').textContent(), /110%/);
  await page.locator('[data-action="agentAutoLayout"]').click();
  assert.equal(await page.locator('.agent-graph-minimap i').count(), 9);
  assert.match(await page.locator('.agent-accessible-topology').textContent(), /agent-node:identity/);
  const identityBehaviorEdge = 'agent-edge:b1e49b51df89541fc360';
  const connectionCount = await page.locator('.agent-accessible-topology [data-action="agentRemoveEdge"]').count();
  await page.locator(`[data-action="agentRemoveEdge"][data-edge-id="${identityBehaviorEdge}"]`).click();
  assert.equal(await page.locator('.agent-accessible-topology [data-action="agentRemoveEdge"]').count(), connectionCount - 1);
  assert.match(await page.locator('[data-studio-validation]').textContent(), /closed executable topology/i);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isDisabled(), true, 'an incomplete working AgentSpec topology must not save');
  await page.locator('[data-action="agentPortConnect"][data-node-id="agent-node:identity"][data-port="out:definition"]').click();
  assert.match(await page.locator('.agent-connection-status').textContent(), /identity\.out:definition/i);
  await page.locator('[data-action="agentPortConnect"][data-node-id="agent-node:behavior"][data-port="in:definition"]').click();
  assert.equal(await page.locator(`.agent-accessible-topology [data-edge-id="${identityBehaviorEdge}"]`).count(), 1);
  assert.equal(await page.locator('.agent-accessible-topology [data-action="agentRemoveEdge"]').count(), connectionCount);
  assert.match(await page.locator('[data-studio-validation]').textContent(), /passes browser preflight/i);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isEnabled(), true);
  await page.locator('[data-agent-node-id="agent-node:identity"]').click();
  assert.match(await page.locator('[data-studio-validation]').textContent(), /passes browser preflight/i);
  const identityX = Number(await page.locator('[data-agent-node-id="agent-node:identity"]').getAttribute('data-agent-x'));
  await page.locator('[data-agent-node-id="agent-node:identity"]').focus();
  await page.keyboard.press('Alt+ArrowRight');
  assert.equal(Number(await page.locator('[data-agent-node-id="agent-node:identity"]').getAttribute('data-agent-x')), identityX + 10);
  await page.locator('[data-action="agentAddTopologyNode"][data-agent-kind="tools"]').click();
  assert.equal(await page.locator('.agent-graph-node').count(), 10);
  assert.equal(await page.locator('.agent-graph-node[data-agent-node-id="agent-node:tools"]').getAttribute('aria-pressed'), 'true');
  await page.locator('[data-agent-node-kind]').selectOption('memory');
  assert.equal(await page.locator('.agent-graph-node[data-agent-node-id="agent-node:tools"]').count(), 0);
  assert.equal(await page.locator('.agent-graph-node[data-agent-node-id="agent-node:memory"]').count(), 1);
  await page.locator('[data-action="agentRemoveTopologyNode"]').click();
  assert.equal(await page.locator('.agent-graph-node').count(), 9);
  await page.locator('[data-action="agentAddBinding"]').click();
  await page.locator('[data-action="agentAddGrant"]').click();
  assert.equal(await page.locator('.agent-builder-card:not(.grant)').count(), 2);
  assert.equal(await page.locator('.agent-builder-card.grant').count(), 2);
  const restrictedCapability = page.locator('[data-agent-binding-field="capability_id"]').last();
  await restrictedCapability.fill('enterprise:restricted-worker');
  assert.match(await page.locator('[data-studio-validation]').textContent(), /px-standard domain boundary/i);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isDisabled(), true);
  await restrictedCapability.fill('capability:bounded-worker');
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isEnabled(), true);
  await page.locator('[data-agent-root-field="instructions"]').fill('Operate inside the explicit task, binding, and effect grant only.');
  await page.locator('[data-action="studioEditorTab"][data-tab="json"]').click();
  assert.match(await page.locator('#studio-draft-json').inputValue(), /capability:bounded-worker/);
  assert.match(await page.locator('#studio-draft-json').inputValue(), /explicit task/);
  const canonicalAgent = JSON.parse(await page.locator('#studio-draft-json').inputValue());
  canonicalAgent.extension_note = 'round-trip-preserved';
  await page.locator('#studio-draft-json').fill(JSON.stringify(canonicalAgent));
  await page.locator('[data-action="studioApplyJson"]').click();
  await page.locator('[data-action="studioEditorTab"][data-tab="json"]').click();
  assert.match(await page.locator('#studio-draft-json').inputValue(), /round-trip-preserved/);
  await page.keyboard.press('Escape');

  await page.locator('.catalog-row[data-kind="agents"]').first().click();
  await page.locator('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
  await page.locator('.agent-builder-layout').waitFor({ state: 'visible' });
  const createCountBeforeLineageAttack = await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'createStudioDraft').length);
  await page.locator('[data-action="studioEditorTab"][data-tab="json"]').click();
  const predecessorJson = JSON.parse(await page.locator('#studio-draft-json').inputValue());
  predecessorJson.agent_id = 'agent:substituted-through-json';
  predecessorJson.version = '9.9.9';
  await page.locator('#studio-draft-json').fill(JSON.stringify(predecessorJson));
  await page.locator('[data-action="studioApplyJson"]').click();
  assert.match(await page.locator('#studio-draft-json').evaluate(element => element.validationMessage), /Predecessor-bound JSON cannot change/);
  assert.equal(await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'createStudioDraft').length), createCountBeforeLineageAttack, 'rejected JSON must not dispatch a create');
  await page.locator('[data-action="studioEditorTab"][data-tab="visual"]').click();
  await page.locator('[data-action="studioEditorTab"][data-tab="json"]').click();
  const retainedPredecessorJson = JSON.parse(await page.locator('#studio-draft-json').inputValue());
  assert.equal(retainedPredecessorJson.agent_id, 'agent:preview-catalog');
  assert.equal(retainedPredecessorJson.version, '1.0.1');
  const forkProof = await page.evaluate(() => {
    const releaseCount = window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'releaseStudioTrust').length;
    document.querySelector('[data-action="forkStudioCandidate"]').click();
    return { releaseCount, latest: [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'releaseStudioTrust') };
  });
  assert.equal(await page.locator('#studio-identity').inputValue(), 'agent:preview-catalog-fork');
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.0');
  assert.equal(await page.locator('#studio-identity').getAttribute('readonly'), null);
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), null);
  assert.match(await page.locator('.identity-warning[role="status"]').textContent(), /INDEPENDENT FORK DRAFT.*grant no lineage, allocation, admission, or authority/s);
  assert.match(forkProof.latest.proof, /^version-allocation:/);
  assert.equal(await page.locator('[data-action="forkStudioCandidate"]').count(), 0);
  await page.keyboard.press('Escape');

  await page.goto(`${preview}?surface=skillsTools`); await settled(page);
  const capabilityScopes = [
    ['PX Native', 'skills'], ['Preserved Originals', 'preserved-skills'], ['Microsoft / Vendor', 'microsoft-skills'],
    ['Enterprise Restricted', 'enterprise-skills'], ['Tools', 'tools']
  ];
  for (const [label, kind] of capabilityScopes) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await page.locator(`.catalog-row[data-kind="${kind}"]`).first().waitFor({ state: 'visible' });
    assert.equal(await page.locator(`.catalog-tabs [data-action="capabilityTab"][data-kind="${kind}"]`).getAttribute('aria-pressed'), 'true');
    assert.ok(await page.locator(`.catalog-row[data-kind="${kind}"]`).count() >= 1, `${label} must populate its separate catalog`);
  }
  await page.getByRole('button', { name: 'PX Native', exact: true }).click();
  await page.locator('.catalog-row[data-kind="skills"]').first().click();
  assert.equal(await page.locator('[data-action="loadSkillPackageEditor"]').count(), 0, 'an unattested external package stays read-only');
  assert.match(await page.locator('.modal-note').last().textContent(), /independent full-tree attestation/i);
  await page.keyboard.press('Escape');
  await page.locator('.catalog-row[data-kind="skills"]').nth(1).click();
  const cancelledPackageRequest = await page.evaluate(() => {
    document.querySelector('[data-action="loadSkillPackageEditor"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadSkillPackageEditor');
    document.querySelector('[data-action="closeModal"]').click();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'skillPackageEditorResult', requestId: request.requestId, catalogKind: request.catalogKind, recordId: request.recordId, sourceSelectionId: 'source-selection:cancelled', selection: {}, result: { treeSha256: '9'.repeat(64), fileCount: 0, editor_files: {} } } }));
    return request;
  });
  assert.match(cancelledPackageRequest.requestId, /^[a-zA-Z0-9._:-]{1,200}$/);
  await page.waitForTimeout(35);
  assert.equal(await page.locator('#studio-skill-file').count(), 0);
  await page.locator('.catalog-row[data-kind="skills"]').nth(1).click();
  const activePackageProbe = await page.evaluate(() => {
    document.querySelector('[data-action="loadSkillPackageEditor"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadSkillPackageEditor');
    const result = { treeSha256: '9'.repeat(64), fileCount: 0, editor_files: {} };
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'loadSkillPackageEditor', requestId: 'stale-package-error', catalogKind: request.catalogKind, recordId: request.recordId, error: 'Synthetic stale package failure.' } }));
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'skillPackageEditorResult', requestId: 'stale-package-load', catalogKind: request.catalogKind, recordId: request.recordId, sourceSelectionId: 'source-selection:stale', selection: {}, result } }));
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'skillPackageEditorResult', requestId: request.requestId, catalogKind: request.catalogKind, recordId: `${request.recordId}-other`, sourceSelectionId: 'source-selection:wrong', selection: {}, result } }));
    return { request, loading: document.querySelector('.cleanup-loading')?.textContent || '' };
  });
  assert.notEqual(activePackageProbe.request.requestId, cancelledPackageRequest.requestId);
  assert.equal(activePackageProbe.request.catalogKind, 'skills');
  assert.match(activePackageProbe.loading, /Resolving the exact catalog record/);
  await page.waitForFunction(() => window.__PX_POSTED_MESSAGES__.some(message => message.type === 'studioOperation' && message.kind === 'skill' && message.operation === 'next-version'));
  const wrongFamilySkillFailure = await page.evaluate(() => {
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'studioOperation' && message.kind === 'skill' && message.operation === 'next-version');
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'loadStudioRevisionEditor', requestId: request.requestId, kind: request.kind, error: 'Synthetic wrong-family revision-load failure.' } }));
    return { requestId: request.requestId, loading: document.querySelector('.cleanup-loading')?.textContent || '' };
  });
  assert.match(wrongFamilySkillFailure.loading, /Checking the exact physical revision set/);
  await page.locator('#studio-skill-file').waitFor({ state: 'visible' });
  const importedSkillAllocationRequest = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'studioOperation' && message.kind === 'skill' && message.operation === 'next-version'));
  assert.deepEqual(Object.keys(importedSkillAllocationRequest.payload).sort(), ['identity', 'source_selection_id', 'source_version']);
  assert.match(importedSkillAllocationRequest.payload.source_selection_id, /^source-selection:/);
  assert.match(await page.locator('#studio-skill-file').inputValue(), /Existing Skill/);
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.1');
  assert.equal(await page.locator('#studio-identity').getAttribute('readonly'), '');
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), '');
  assert.match(await page.locator('.skill-diff').textContent(), /new immutable revision/i);
  await page.locator('#studio-skill-file').fill(`${await page.locator('#studio-skill-file').inputValue()}\nDraft survives conflict.\n`);
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioOperationResult', requestId: 'stale-allocation', kind: 'agent', operation: 'next-version', result: { schema_version: 'wrong' } } })));
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.1');
  await page.locator('[data-control-id="studio-save-candidate"]').click();
  const saveRequest = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'createStudioDraft'));
  assert.match(saveRequest.requestId, /^[a-zA-Z0-9._:-]{1,200}$/);
  assert.equal(saveRequest.kind, 'skill');
  assert.match(saveRequest.payload.version_allocation_proof, /^version-allocation:/);
  assert.equal(saveRequest.payload.version_allocation.source_revision_sha256, '6'.repeat(64));
  assert.equal(saveRequest.payload.version_allocation.source_content_sha256, '9'.repeat(64));
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftCancelled', requestId: 'stale-save-request', kind: 'skill' } })));
  const catalogQueriesBeforeStaleSaveResponses = await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'catalogQuery').length);
  await page.evaluate(requestId => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftResult', requestId, kind: 'agent', result: { created: true } } })), saveRequest.requestId);
  await page.evaluate(requestId => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftOutcomeUnverified', requestId, kind: 'workflow', warnings: ['stale-cross-kind'] } })), saveRequest.requestId);
  assert.equal(await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'catalogQuery').length), catalogQueriesBeforeStaleSaveResponses, 'unmatched save responses must not invalidate or requery any catalog');
  assert.match(await page.locator('#studio-skill-file').inputValue(), /Draft survives conflict/);
  assert.match(await page.locator('[data-control-id="studio-save-candidate"]').textContent(), /Awaiting host approval/);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isDisabled(), true);
  await page.evaluate(requestId => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioVersionConflict', requestId, kind: 'skill', error: 'Another immutable revision was published.', allocationProof: 'version-allocation:conflict-proof', allocation: { schema_version: 'px.studio-version-allocation/1.0', kind: 'skill', identity: 'skill:project-studio-preview', source_version: '1.0.0', source_scope: 'studio-physical', source_revision_sha256: '6'.repeat(64), source_content_sha256: '9'.repeat(64), candidate_version: '1.0.2', occupied_versions_sha256: '7'.repeat(64), observed_utc: '2026-08-16T00:00:01Z' } } })), saveRequest.requestId);
  assert.match(await page.locator('#studio-skill-file').inputValue(), /Draft survives conflict/);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isDisabled(), true);
  await page.locator('[data-action="acceptStudioVersionSuggestion"]').click();
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.2');
  assert.match(await page.locator('#studio-skill-file').inputValue(), /Draft survives conflict/);
  await page.locator('[data-action="skillSelectFile"][data-file-path="skill.yaml"]').click();
  assert.match(await page.locator('#studio-skill-file').inputValue(), /version:\s*1\.0\.2/);
  await page.locator('[data-action="skillSelectFile"][data-file-path="SKILL.md"]').click();
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isEnabled(), true);
  await page.locator('[data-control-id="studio-save-candidate"]').click();
  const retrySaveRequest = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'createStudioDraft'));
  assert.notEqual(retrySaveRequest.requestId, saveRequest.requestId);
  assert.equal(retrySaveRequest.kind, 'skill');
  assert.match(retrySaveRequest.payload.editor_files['skill.yaml'], /version:\s*1\.0\.2/);
  assert.equal(JSON.parse(retrySaveRequest.payload.editor_files['capability.json']).version, '1.0.2');
  await page.evaluate(requestId => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioVersionConflict', requestId, kind: 'skill', error: 'Predecessor binding changed.', allocation: { schema_version: 'px.studio-version-allocation/1.0', kind: 'skill', identity: 'skill:existing', source_version: '1.0.0', source_scope: 'studio-physical', source_revision_sha256: '6'.repeat(64), source_content_sha256: 'a'.repeat(64), candidate_version: '1.0.3', occupied_versions_sha256: 'b'.repeat(64), observed_utc: '2026-08-16T00:00:02Z' } } })), retrySaveRequest.requestId);
  assert.match(await page.locator('[data-control-id="studio-save-candidate"]').textContent(), /Version check failed/);
  await page.keyboard.press('Escape');
  await page.locator('[data-action="openStudioDraft"][data-kind="skill"]').click();
  assert.match(await page.locator('#modal-root').textContent(), /Recover unsaved Studio draft/);
  await page.locator('[data-action="discardWorkingStudioDraft"][data-kind="skill"]').click();
  assert.equal(await page.locator('.skill-file-tree').isVisible(), true);
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), null);
  assert.equal(await page.locator('.skill-file-tree > button').count(), 6);
  await page.locator('[data-action="skillAddFile"][data-file-kind="resource"]').click();
  await page.locator('#studio-skill-file').fill('# Bounded reference\n');
  await page.locator('#studio-identity').fill('synchronized-skill');
  await page.locator('#studio-version').fill('2.0.0');
  assert.match(await page.locator('[data-studio-validation]').textContent(), /pass/i);
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isVisible(), true);
  const fallbackSkillPayload = await page.evaluate(() => {
    const input = document.createElement('textarea'); input.id = 'studio-draft-json';
    input.value = JSON.stringify({ skill_id: 'old-skill', version: '1.0.0', owner: 'human:owner', editor_files: { 'SKILL.md': '---\nname: old-skill\ndescription: Browser fallback owner.\n---\n', 'capability.json': '{"id":"old-skill","version":"1.0.0"}\n', 'skill.yaml': 'id: old-skill\nversion: 1.0.0\n' } });
    document.body.append(input);
    try { return window.studioPayload(document.querySelector('[data-control-id="studio-save-candidate"]')); } finally { input.remove(); }
  });
  assert.equal(fallbackSkillPayload.skill_id, 'synchronized-skill');
  assert.equal(fallbackSkillPayload.version, '2.0.0');
  assert.equal(JSON.parse(fallbackSkillPayload.editor_files['capability.json']).id, 'synchronized-skill');
  await page.locator('[data-control-id="studio-save-candidate"]').click();
  const synchronizedSkillRequest = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'createStudioDraft'));
  assert.equal(synchronizedSkillRequest.payload.skill_id, 'synchronized-skill');
  assert.equal(synchronizedSkillRequest.payload.version, '2.0.0');
  assert.equal(JSON.parse(synchronizedSkillRequest.payload.editor_files['capability.json']).id, 'synchronized-skill');
  assert.equal(JSON.parse(synchronizedSkillRequest.payload.editor_files['capability.json']).version, '2.0.0');
  assert.match(synchronizedSkillRequest.payload.editor_files['skill.yaml'], /id:\s*synchronized-skill/);
  assert.match(synchronizedSkillRequest.payload.editor_files['skill.yaml'], /version:\s*2\.0\.0/);
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(requestId => [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'detachStudioDraft' && message.requestId === requestId && message.kind === 'skill'), synchronizedSkillRequest.requestId), true);
  const catalogQueriesBeforeUnverified = await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'catalogQuery' && message.kind === 'skills').length);
  await page.evaluate(request => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftOutcomeUnverified', requestId: request.requestId, kind: request.kind, warnings: ['receipt-invalid'] } })), synchronizedSkillRequest);
  await page.waitForTimeout(35);
  assert.ok(await page.evaluate(() => window.__PX_POSTED_MESSAGES__.filter(message => message.type === 'catalogQuery' && message.kind === 'skills').length) > catalogQueriesBeforeUnverified);
  assert.equal(await page.locator('[role="dialog"]').count(), 0, 'detached unverified outcome must recover the catalog without reopening the editor');
  await page.evaluate(request => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'createStudioDraft', requestId: request.requestId, kind: request.kind, error: 'late detached host failure' } })), synchronizedSkillRequest);
  assert.equal(await page.locator('[role="dialog"]').count(), 0, 'detached save must reject a late correlated host error without reopening a modal');
  await page.locator('.catalog-row[data-kind="skills"]').nth(1).click();
  await page.locator('[data-action="loadSkillPackageEditor"]').click();
  await page.locator('#studio-skill-file').waitFor({ state: 'visible' });
  const projectSkillRequests = await page.evaluate(() => {
    const messages = [...window.__PX_POSTED_MESSAGES__].reverse();
    return {
      load: messages.find(message => message.type === 'loadSkillPackageEditor'),
      allocation: messages.find(message => message.type === 'studioOperation' && message.kind === 'skill' && message.operation === 'next-version')
    };
  });
  assert.equal(projectSkillRequests.load.catalogKind, 'skills');
  assert.deepEqual(Object.keys(projectSkillRequests.allocation.payload).sort(), ['identity', 'source_selection_id', 'source_version']);
  const physicalHashAuthorityFixture = await page.evaluate(() => window.__PX_PREVIEW_ALLOCATION_FIXTURE__);
  assert.notEqual(physicalHashAuthorityFixture.projectStudioPackageTreeSha256, physicalHashAuthorityFixture.physicalSourceContentSha256);
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.1');
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), '');
  assert.equal(await page.locator('.studio-revision-baseline').isVisible(), true);
  await page.keyboard.press('Escape');

  await page.goto(`${preview}?surface=knowledgeGraph`); await settled(page);
  await page.locator('[data-graph-analysis]').selectOption('hubs');
  await page.locator('[data-graph-search]').fill('contradiction');
  await page.locator('[data-graph-search]').press('Enter'); await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-graph-search]')), true);
  assert.deepEqual(await page.locator('[data-graph-search]').evaluate(element => ({ value: element.value, start: element.selectionStart, end: element.selectionEnd })), { value: 'contradiction', start: 13, end: 13 });
  assert.ok(await page.locator('.graph-node.actual').count() >= 10);
  assert.ok(await page.locator('.relationship-row').count() >= 10);
  const graphCanvas = page.locator('[data-graph-canvas]');
  await graphCanvas.waitFor({ state: 'visible' });
  assert.equal(await page.locator('[data-action="graphLayout"][data-layout="flow"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('[style]').count(), 0, 'dashboard DOM must not contain inline style attributes');
  const initialLayout = await page.locator('[data-graph-scene]').evaluate(element => {
    const node = element.querySelector('.graph-node.actual'); const sceneStyle = getComputedStyle(element); const nodeStyle = node ? getComputedStyle(node) : null;
    return { transform: sceneStyle.transform, width: Number.parseFloat(sceneStyle.width), height: Number.parseFloat(sceneStyle.height), x: Number.parseFloat(nodeStyle?.getPropertyValue('--x') || ''), y: Number.parseFloat(nodeStyle?.getPropertyValue('--y') || ''), adoptedSheets: document.adoptedStyleSheets.length };
  });
  assert.ok(initialLayout.adoptedSheets >= 1);
  for (const value of [initialLayout.width, initialLayout.height, initialLayout.x, initialLayout.y]) assert.equal(Number.isFinite(value), true, JSON.stringify(initialLayout));
  const initialTransform = initialLayout.transform;
  const invalidGraphLayout = await page.locator('[data-graph-scene]').evaluate(element => {
    const original = { width: element.dataset.sceneWidth, height: element.dataset.sceneHeight, x: element.dataset.graphTranslateX, y: element.dataset.graphTranslateY, scale: element.dataset.graphScale };
    element.dataset.sceneWidth = 'Infinity'; element.dataset.sceneHeight = '-Infinity'; element.dataset.graphTranslateX = 'NaN'; element.dataset.graphTranslateY = '1e999'; element.dataset.graphScale = 'Infinity';
    window.PXDashboard.require('boundedLayout').apply(element);
    const style = getComputedStyle(element); const matrix = new DOMMatrixReadOnly(style.transform);
    const result = { width: Number.parseFloat(style.width), height: Number.parseFloat(style.height), scale: matrix.a, x: matrix.e, y: matrix.f };
    element.dataset.sceneWidth = original.width; element.dataset.sceneHeight = original.height; element.dataset.graphTranslateX = original.x; element.dataset.graphTranslateY = original.y; element.dataset.graphScale = original.scale;
    window.PXDashboard.require('boundedLayout').apply(element);
    return result;
  });
  assert.deepEqual(invalidGraphLayout, { width: 1280, height: 780, scale: 1, x: 0, y: 0 });
  assert.equal(await page.locator('[style]').count(), 0, 'invalid data must not fall back to an inline style');
  await page.locator('[data-action="graphZoomIn"]').click();
  assert.notEqual(await page.locator('[data-graph-scene]').evaluate(element => getComputedStyle(element).transform), initialTransform);
  assert.match(await page.locator('[data-graph-zoom]').textContent(), /%/);
  await graphCanvas.hover(); await page.mouse.wheel(48, 32);
  assert.match(await page.locator('[data-graph-status]').textContent(), /panned/i);
  const beforeTrackpadPinch = await page.locator('[data-graph-scene]').evaluate(element => getComputedStyle(element).transform);
  await page.keyboard.down('Control'); await page.mouse.wheel(0, -90); await page.keyboard.up('Control');
  assert.notEqual(await page.locator('[data-graph-scene]').evaluate(element => getComputedStyle(element).transform), beforeTrackpadPinch);
  const box = await graphCanvas.boundingBox();
  await page.mouse.move(box.x + box.width * .55, box.y + box.height * .55); await page.mouse.down();
  await page.mouse.move(box.x + box.width * .62, box.y + box.height * .61, { steps: 3 }); await page.mouse.up();
  assert.match(await page.locator('[data-graph-status]').textContent(), /panned/i);
  const beforePinch = await page.locator('[data-graph-scene]').evaluate(element => getComputedStyle(element).transform);
  await graphCanvas.dispatchEvent('pointerdown', { pointerId: 21, pointerType: 'touch', isPrimary: true, clientX: box.x + 250, clientY: box.y + 260, buttons: 1 });
  await graphCanvas.dispatchEvent('pointerdown', { pointerId: 22, pointerType: 'touch', isPrimary: false, clientX: box.x + 390, clientY: box.y + 260, buttons: 1 });
  await graphCanvas.dispatchEvent('pointermove', { pointerId: 22, pointerType: 'touch', isPrimary: false, clientX: box.x + 450, clientY: box.y + 260, buttons: 1 });
  await graphCanvas.dispatchEvent('pointerup', { pointerId: 22, pointerType: 'touch', isPrimary: false, clientX: box.x + 450, clientY: box.y + 260 });
  await graphCanvas.dispatchEvent('pointerup', { pointerId: 21, pointerType: 'touch', isPrimary: true, clientX: box.x + 250, clientY: box.y + 260 });
  assert.notEqual(await page.locator('[data-graph-scene]').evaluate(element => getComputedStyle(element).transform), beforePinch);
  await graphCanvas.focus(); await page.keyboard.press('+');
  await page.keyboard.press('0'); assert.match(await page.locator('[data-graph-status]').textContent(), /fitted/i);
  await page.locator('[data-action="graphLayout"][data-layout="orbit"]').click();
  assert.equal(await page.locator('[data-action="graphLayout"][data-layout="orbit"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('[style]').count(), 0, 'graph layout rerender must not introduce inline styles');
  assert.equal(await page.locator('.graph-node.actual').evaluateAll(nodes => nodes.every(node => {
    const style = getComputedStyle(node); return Number.isFinite(Number.parseFloat(style.getPropertyValue('--x'))) && Number.isFinite(Number.parseFloat(style.getPropertyValue('--y')));
  })), true);
  await page.locator('[data-action="graphToggleInspector"]').click();
  assert.equal(await page.locator('.relationship-inspector').isVisible(), false);
  await page.locator('[data-action="graphToggleInspector"]').click();
  await page.locator('[data-action="graphFocus"]').click();
  assert.equal(await page.locator('.graph-panel').evaluate(element => element.classList.contains('graph-focus-mode')), true);
  await page.waitForTimeout(20);
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-graph-canvas]')), true);
  await page.locator('.graph-minimap').click();
  assert.match(await page.locator('[data-graph-status]').textContent(), /fitted|readable/i);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.graph-panel').evaluate(element => element.classList.contains('graph-focus-mode')), false);
  await page.waitForTimeout(20);
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-action="graphFocus"]')), true);
  await page.locator('.graph-node.actual').nth(1).hover();
  assert.ok(await page.locator('.graph-edge-group.is-highlighted').count() >= 1);
  await page.locator('.graph-node.actual').nth(1).click(); await page.waitForTimeout(80);
  assert.equal(await page.locator('[data-action="graphBack"]').isEnabled(), true);
  await page.locator('[data-action="graphBack"]').click(); await page.waitForTimeout(80);
  await page.locator('[data-action="graphSaveView"]').click();
  await page.locator('#graph-view-name').fill('Contradiction review');
  await page.locator('[data-action="submitGraphSavedView"]').click();
  assert.equal(await page.locator('[data-action="graphApplySavedView"]').first().textContent(), 'Contradiction review');
  await page.locator('[data-action="graphDeleteSavedView"]').first().click();
  assert.equal(await page.locator('[data-action="graphApplySavedView"]').count(), 0);

  await page.goto(`${preview}?surface=workflows`); await settled(page);
  await page.locator('.catalog-row[data-kind="workflows"]').first().click();
  // UI interaction evidence only: this confirms request-bound editor attachment, not a real host write.
  const failedWorkflowAllocation = await page.evaluate(() => {
    document.querySelector('[data-action="openStudioFromCatalog"][data-kind="workflow"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadStudioRevisionEditor' && message.kind === 'workflow');
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'loadStudioRevisionEditor', requestId: request.requestId, kind: 'workflow', catalogKind: request.catalogKind, recordId: request.recordId, error: 'Synthetic exact allocation failure.' } }));
    return request.requestId;
  });
  assert.match(failedWorkflowAllocation, /^[a-zA-Z0-9._:-]{1,200}$/);
  assert.match(await page.locator('.modal-body').textContent(), /Synthetic exact allocation failure/);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(30);
  await page.locator('.catalog-row[data-kind="workflows"]').first().click();
  await page.locator('[data-action="openStudioFromCatalog"][data-kind="workflow"]').click();
  await page.locator('[data-control-id="workflow-canvas"]').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#studio-identity').getAttribute('readonly'), '');
  assert.equal(await page.locator('#studio-version').getAttribute('readonly'), '');
  assert.equal(await page.locator('#studio-version').inputValue(), '1.0.1');
  assert.equal(await page.locator('.studio-revision-baseline').isVisible(), true);
  await page.locator('[data-control-id="studio-save-candidate"]').click();
  const predecessorWorkflowSave = await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'createStudioDraft' && message.kind === 'workflow'));
  assert.equal(predecessorWorkflowSave.payload.workflow_id, 'workflow:preview-catalog');
  assert.equal(predecessorWorkflowSave.payload.version, '1.0.1');
  assert.equal(predecessorWorkflowSave.payload.version_allocation.identity, 'workflow:preview-catalog');
  assert.equal(predecessorWorkflowSave.payload.version_allocation.source_scope, 'studio-physical');
  assert.match(predecessorWorkflowSave.payload.version_allocation_proof, /^version-allocation:/);
  assert.equal(predecessorWorkflowSave.payload.version_allocation.candidate_version, '1.0.1');
  await page.keyboard.press('Escape');
  await page.evaluate(request => window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftResult', requestId: request.requestId, kind: request.kind, result: { created: true } } })), predecessorWorkflowSave);
  assert.equal(await page.locator('[role="dialog"]').count(), 0, 'Escape cancellation must reject a late predecessor-workflow save result');
  await page.locator('[data-action="openStudioDraft"][data-kind="workflow"]').click();
  assert.equal(await page.locator('[data-control-id="workflow-canvas"]').isVisible(), true);
  const initialWorkflowLayout = await page.locator('[data-control-id="workflow-canvas"]').evaluate(canvas => {
    const node = canvas.querySelector('.workflow-editor-node'); const canvasStyle = getComputedStyle(canvas); const nodeStyle = getComputedStyle(node);
    return { scale: Number.parseFloat(canvasStyle.getPropertyValue('--workflow-scale')), x: Number.parseFloat(nodeStyle.getPropertyValue('--wx')), y: Number.parseFloat(nodeStyle.getPropertyValue('--wy')) };
  });
  assert.equal(initialWorkflowLayout.scale, 1);
  assert.equal(Number.isFinite(initialWorkflowLayout.x) && Number.isFinite(initialWorkflowLayout.y), true, JSON.stringify(initialWorkflowLayout));
  assert.equal(await page.locator('[style]').count(), 0);
  await page.locator('[data-action="workflowAddBinding"]').click();
  await page.locator('[data-action="workflowAddGrant"]').click();
  assert.equal(await page.locator('[data-workflow-binding-index]').count(), 2);
  assert.equal(await page.locator('[data-workflow-grant-index]').count(), 2);
  await page.locator('[data-workflow-binding-adapter]').last().selectOption('double');
  await page.locator('[data-workflow-binding-field="cost_policy"]').last().fill('bounded-local');
  await page.locator('[data-workflow-binding-field="egress_policy"]').last().selectOption('loopback-only');
  await page.locator('[data-workflow-binding-field="evidence_refs"]').last().fill('receipt:binding-edited');
  await page.locator('[data-workflow-grant-field="evidence_refs"]').last().fill('receipt:grant-edited');
  await page.locator('[data-workflow-binding-field="effect_grant_ids"]').last().fill('grant:workflow-2');
  await page.locator('[data-workflow-field="executor_binding_id"]').fill('binding:workflow-2');
  await page.locator('[data-workflow-field="executor_binding_id"]').press('Tab');
  await page.locator('[data-workflow-field="effect_grant_ids"]').fill('grant:workflow-2');
  await page.locator('[data-workflow-field="effect_grant_ids"]').press('Tab');
  const bindingIdentity = page.locator('[data-workflow-binding-field="binding_id"]').last();
  await bindingIdentity.fill('binding:my-workflow');
  assert.match(await bindingIdentity.evaluate(element => element.validationMessage), /unique/i);
  await bindingIdentity.fill('binding:renamed');
  const grantIdentity = page.locator('[data-workflow-grant-field="grant_id"]').last();
  await grantIdentity.fill('grant:my-workflow');
  assert.match(await grantIdentity.evaluate(element => element.validationMessage), /unique/i);
  await grantIdentity.fill('grant:renamed');
  assert.equal(await page.locator('[data-control-id="studio-save-candidate"]').isEnabled(), true);
  await page.locator('[data-action="workflowAddNode"][data-node-template="validation"]').click();
  assert.equal(await page.locator('.workflow-editor-node').count(), 2);
  const rerenderedWorkflowLayout = await page.locator('.workflow-editor-node').evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node); return [Number.parseFloat(style.getPropertyValue('--wx')), Number.parseFloat(style.getPropertyValue('--wy'))];
  }));
  assert.equal(rerenderedWorkflowLayout.flat().every(Number.isFinite), true, JSON.stringify(rerenderedWorkflowLayout));
  assert.equal(await page.locator('[style]').count(), 0, 'workflow rerender must retain CSP-safe CSSOM geometry');
  const invalidWorkflowLayout = await page.locator('.studio-editor-root').evaluate(root => {
    const canvas = root.querySelector('[data-control-id="workflow-canvas"]'); const node = root.querySelector('.workflow-editor-node');
    const original = { scale: canvas.dataset.workflowScale, x: node.dataset.workflowX, y: node.dataset.workflowY };
    canvas.dataset.workflowScale = 'Infinity'; node.dataset.workflowX = 'NaN'; node.dataset.workflowY = '-Infinity';
    window.PXDashboard.require('boundedLayout').apply(root);
    const canvasStyle = getComputedStyle(canvas); const nodeStyle = getComputedStyle(node);
    const result = { scale: Number.parseFloat(canvasStyle.getPropertyValue('--workflow-scale')), x: Number.parseFloat(nodeStyle.getPropertyValue('--wx')), y: Number.parseFloat(nodeStyle.getPropertyValue('--wy')) };
    canvas.dataset.workflowScale = original.scale; node.dataset.workflowX = original.x; node.dataset.workflowY = original.y;
    window.PXDashboard.require('boundedLayout').apply(root);
    return result;
  });
  assert.deepEqual(invalidWorkflowLayout, { scale: 1, x: 40, y: 40 });
  await page.locator('[data-action="workflowMoveNode"][data-delta="-1"]').click();
  await page.locator('[data-edge-source-endpoint]').selectOption('step:validate-2|value');
  await page.locator('[data-edge-target-endpoint]').selectOption('step:one|value');
  await page.locator('[data-action="workflowConnectNodes"]').click();
  assert.equal(await page.locator('.workflow-edge-editor li').count(), 1);
  await page.locator('[data-action="studioEditorTab"][data-tab="json"]').click();
  assert.equal(await page.locator('#studio-draft-json').isVisible(), true);
  assert.match(await page.locator('#studio-draft-json').inputValue(), /step:validate-2/);
  const workflowAuthorityDraft = JSON.parse(await page.locator('#studio-draft-json').inputValue());
  const editedBinding = workflowAuthorityDraft.bindings.find(item => item.binding_id === 'binding:renamed');
  const editedGrant = workflowAuthorityDraft.grants.find(item => item.grant_id === 'grant:renamed');
  assert.deepEqual({ adapter: workflowAuthorityDraft.executor_adapters['binding:renamed'], grants: editedBinding.effect_grant_ids, cost: editedBinding.cost_policy, egress: editedBinding.egress_policy, evidence: editedBinding.evidence_refs, state: editedBinding.state }, { adapter: 'double', grants: ['grant:renamed'], cost: 'bounded-local', egress: 'loopback-only', evidence: ['receipt:binding-edited'], state: 'admitted' });
  assert.deepEqual({ evidence: editedGrant.evidence_refs, state: editedGrant.state }, { evidence: ['receipt:grant-edited'], state: 'admitted' });
  assert.equal(workflowAuthorityDraft.nodes.some(node => node.executor_binding_id === 'binding:renamed' && node.effect_grant_ids.includes('grant:renamed')), true);
  assert.equal(workflowAuthorityDraft.authority_definition_state, 'supplied-for-new-revision');
  await page.keyboard.press('Escape');
  await page.locator('[data-action="newParallelPlan"]').click();
  await page.locator('#plan-objective').fill('Playwright interaction audit');
  await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: window.__PX_TEST_SNAPSHOT__, coordination: null, settings: { showAdvancedSurfaces: true, glassIntensity: .66 } } })));
  assert.equal(await page.locator('#plan-objective').inputValue(), 'Playwright interaction audit');
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'plan-objective');
  await page.locator('#plan-tasks').fill('ui | Audit UI | | media/ | VS Code | visual agent | 1000 | workspace-read');
  await page.locator('[data-action="submitParallelPlan"]').click();
  assert.equal(await page.locator('[role="dialog"]').count(), 0);
  await page.locator('[data-action="catalogNext"]').click(); await page.waitForTimeout(100);
  assert.match(await page.locator('.catalog-controls > span').textContent(), /51.+72/);
  await page.locator('[data-action="surfaceScope"][data-target="workflows"][data-scope="environment"]').click(); await page.waitForTimeout(80);
  await page.setViewportSize({ width: 480, height: 900 });
  for (const label of ['Dashboard', 'Projects', 'Agents', 'Knowledge Graph', 'Skills & Tools', 'Workflows', 'Plugin Manager', 'Memory', 'Activity', 'Diagnostics', 'Assurance', 'Settings']) {
    assert.equal(await page.locator('.primary-nav').getByRole('button', { name: label, exact: true }).count(), 1, `narrow navigation must retain the ${label} accessible name`);
  }
  const envSchemaTab = page.locator('[data-action="environmentScope"][data-scope="environment-files"]');
  const envSchemaBox = await envSchemaTab.boundingBox();
  assert.ok(envSchemaBox && envSchemaBox.x >= 0 && envSchemaBox.x + envSchemaBox.width <= 480, 'environment schema tab must remain in the touch viewport');
  await page.locator('[data-action="environmentScope"][data-scope="environments"]').click(); await page.waitForTimeout(80);
  await page.locator('.environment-row').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /read-only discovery record/i);
  await page.locator('[data-action="previewEnvironmentLifecycle"]').click(); await page.waitForTimeout(80);
  assert.equal(await page.locator('#environment-lifecycle-target').inputValue(), '');
  assert.equal(await page.locator('[data-action="executeEnvironmentLifecycle"]').isDisabled(), true);
  await page.locator('#environment-lifecycle-target').fill('C:/workspace/.venv');
  assert.equal(await page.locator('[data-action="executeEnvironmentLifecycle"]').isEnabled(), true);
  await page.keyboard.press('Escape');
  await page.locator('[data-action="environmentScope"][data-scope="environment-files"]').click(); await page.waitForTimeout(80);
  await page.locator('.environment-row').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /values and weak value fingerprints are prohibited/i);
  await page.locator('[data-action="previewEnvironmentLifecycle"]').click(); await page.waitForTimeout(80);
  assert.equal(await page.locator('#environment-lifecycle-consumers').isVisible(), true);
  await page.locator('#environment-lifecycle-target').fill('C:/workspace/.env');
  assert.equal(await page.locator('[data-action="executeEnvironmentLifecycle"]').isDisabled(), true);
  await page.locator('#environment-lifecycle-consumers').check();
  assert.equal(await page.locator('[data-action="executeEnvironmentLifecycle"]').isEnabled(), true);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.goto(`${preview}?surface=plugins`); await settled(page);
  await page.locator('[data-action="inspectMachineManifest"]').first().click();
  await page.locator('[data-tab="machine"]').click();
  assert.match(await page.locator('#info-machine').textContent(), /structured_content/);
  await page.keyboard.press('Escape');

  await page.goto(`${preview}?surface=activity`); await settled(page);
  assert.match(await page.locator('.activity-privacy').textContent(), /Private reasoning and content are not/i);
  assert.ok(await page.locator('.activity-event').count() >= 10);
  await page.locator('.activity-event').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /METADATA ONLY/);
  await page.locator('[data-tab="machine"]').click();
  assert.match(await page.locator('#info-machine').textContent(), /content_captured/);
  await page.keyboard.press('Escape');
  await page.locator('[data-activity-search]').fill('codex'); await page.waitForTimeout(350);
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-activity-search]')), true);
  assert.equal(await page.locator('.activity-toolbar > span:last-child').getAttribute('role'), 'status');
  assert.ok(await page.locator('.activity-event').count() >= 1);

  await page.goto(`${preview}?surface=memory`); await settled(page);
  assert.match(await page.locator('.memory-authority').first().textContent(), /CANONICAL AUTHORITY/);
  assert.match(await page.locator('.memory-authority').nth(1).textContent(), /non-canonical/i);
  await page.locator('[data-memory-search]').fill('decision'); await page.waitForTimeout(350);
  assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-memory-search]')), true);
  await page.locator('.memory-record').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /CANONICAL/);
  await page.locator('[data-tab="machine"]').click();
  assert.match(await page.locator('#info-machine').textContent(), /record_sha256/);
  await page.keyboard.press('Escape');
  await page.locator('[data-action="captureMemory"]').click();
  await page.locator('#memory-content').fill('Playwright-tested proposed record');
  await page.locator('[data-action="submitMemory"]').click();
  assert.equal(await page.locator('[role="dialog"]').count(), 0);

  await page.goto(`${preview}?surface=runtimeCore`); await settled(page);
  await page.locator('[data-action="inspectSensor"]').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /LIVE READ-ONLY SENSOR/);
  await page.keyboard.press('Escape');

  await page.goto(`${preview}?surface=assurance`); await settled(page);
  const readinessLayout = await page.locator('.readiness-meter i').first().evaluate(element => {
    const style = getComputedStyle(element); return { data: Number(element.dataset.readinessScore), score: Number.parseFloat(style.getPropertyValue('--score')), width: Number.parseFloat(style.width) };
  });
  assert.equal(readinessLayout.score, readinessLayout.data);
  assert.equal(Number.isFinite(readinessLayout.width), true);
  if (readinessLayout.score > 0) assert.ok(readinessLayout.width > 0);
  const invalidReadinessLayout = await page.locator('.readiness-meter i').first().evaluate(element => {
    const original = element.dataset.readinessScore; element.dataset.readinessScore = 'Infinity';
    window.PXDashboard.require('boundedLayout').apply(element);
    const style = getComputedStyle(element); const result = { score: Number.parseFloat(style.getPropertyValue('--score')), width: Number.parseFloat(style.width) };
    element.dataset.readinessScore = original; window.PXDashboard.require('boundedLayout').apply(element); return result;
  });
  assert.deepEqual(invalidReadinessLayout, { score: 0, width: 0 });
  assert.equal(await page.locator('[style]').count(), 0);
  await page.locator('[data-action="inspectReadiness"]').first().click();
  assert.match(await page.locator('[role="dialog"]').textContent(), /Evidence/);
  await page.keyboard.press('Escape');

  for (const width of [480, 760, 1050, 1174, 1208, 1440, 1920]) {
    await page.setViewportSize({ width, height: width <= 760 ? 900 : 1000 });
    await page.goto(`${preview}?surface=dashboard`); await settled(page); await noHorizontalOverflow(page, `dashboard-${width}`);
    assert.equal(await page.locator('.control-rail .nav-icon').first().isVisible(), true);
    const logo = await assertContained(page, '.brand-mark', '.brand-frame', `brand-${width}`);
    assert.ok(logo.child.width >= 30 && logo.child.height >= 30, `brand-${width}: rendered mark is too small ${JSON.stringify(logo)}`);
    assert.equal(await page.locator('.brand-mark').evaluate(image => image.complete && image.naturalWidth > 0), true);
    await assertContained(page, '.page-identity', '.cockpit-header', `page-identity-${width}`);
    await assertContained(page, '.cockpit-actions', '.cockpit-header', `cockpit-actions-${width}`);
    await assertHeaderSeparation(page, `cockpit-header-${width}`);
    await assertContained(page, '.hero-copy', '.hero', `hero-copy-${width}`);

    await page.locator('[data-action="inspectMetric"]').first().click();
    await page.locator('[role="dialog"]').waitFor();
    await noHorizontalOverflow(page, `metric-modal-${width}`);
    await assertContained(page, '.information-tabs', '.modal-body', `information-tabs-${width}`);
    await page.locator('[data-tab="machine"]').click();
    assert.equal(await page.locator('#info-machine').isVisible(), true);
    assert.equal(await page.locator('#info-human').isHidden(), true);
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.locator('#info-human').isVisible(), true);
    await page.keyboard.press('Escape');

    await page.goto(`${preview}?surface=knowledgeGraph`); await settled(page); await page.waitForTimeout(180);
    await noHorizontalOverflow(page, `knowledgeGraph-${width}`);
    const readableGraph = await page.locator('[data-graph-scene]').evaluate(element => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(element).transform);
      const firstNode = element.querySelector('.graph-node.actual')?.getBoundingClientRect();
      return { scale: matrix.a, firstNodeWidth: firstNode?.width || 0 };
    });
    const minimumScale = width <= 480 ? .71 : width <= 760 ? .69 : .67;
    assert.ok(readableGraph.scale >= minimumScale, `knowledgeGraph-${width}: initial graph scale is not readable ${JSON.stringify(readableGraph)}`);
    assert.ok(readableGraph.firstNodeWidth >= 108, `knowledgeGraph-${width}: graph labels collapsed below readable geometry ${JSON.stringify(readableGraph)}`);
    assert.equal(await page.locator('[style]').count(), 0, `knowledgeGraph-${width}: rerender introduced inline styles`);
    await assertContained(page, '.graph-selection-card', '.graph-canvas', `graph-selection-${width}`);
    await assertContained(page, '.graph-minimap', '.graph-canvas', `graph-minimap-${width}`);
  }

  await page.setViewportSize({ width: 480, height: 900 });
  for (const surface of ['memory', 'activity', 'workflows', 'plugins', 'diagnostics', 'assurance', 'settings']) {
    await page.goto(`${preview}?surface=${surface}`); await settled(page); await noHorizontalOverflow(page, `${surface}-mobile`);
  }
  await page.goto(`${preview}?surface=settings`); await settled(page);
  await assertContained(page, '.policy-switch', '.surface-settings > .panel:has(.policy-switch)', 'settings-policy-mobile');
  assert.equal(await page.locator('.guardrail-grid').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length), 2);
  assert.deepEqual(failures, []);
  writeVisualManifest(browser.version());
});

test('source-bound Studio recovery reapplies only an exactly reauthenticated overlay', { timeout: 30000 }, async t => {
  const browser = await chromium.launch({ executablePath: browserLane.executablePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  t.after(async () => { await browser.close(); });
  const page = await context.newPage();
  await page.goto(`${preview}?surface=agents`); await settled(page);

  await page.locator('.catalog-row[data-kind="agents"]').first().click();
  await page.locator('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
  const instructions = page.locator('[data-agent-root-field="instructions"]');
  await instructions.waitFor({ state: 'visible' });
  await instructions.fill('Retained exact overlay.');
  await page.waitForTimeout(25);
  await page.keyboard.press('Escape');

  await page.locator('[data-action="openStudioDraft"][data-kind="agent"]').click();
  assert.match(await page.locator('.control-modal').textContent(), /Reopen that exact catalog revision/i);
  await page.locator('.control-modal footer [data-action="closeModal"]').click();
  await page.locator('.catalog-row[data-kind="agents"]').first().click();
  await page.locator('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
  await page.locator('[data-agent-root-field="instructions"]').waitFor({ state: 'visible' });
  assert.equal(await page.locator('[data-agent-root-field="instructions"]').inputValue(), 'Retained exact overlay.');
  assert.match(await page.locator('.studio-revision-baseline').allTextContents().then(values => values.join(' ')), /RETAINED OVERLAY RESTORED/);

  await page.locator('[data-agent-root-field="instructions"]').fill('Overlay must remain retained on mismatch.');
  await page.waitForTimeout(25);
  await page.keyboard.press('Escape');
  await page.locator('.catalog-row[data-kind="agents"]').first().click();
  await page.evaluate(() => {
    document.querySelector('[data-action="openStudioFromCatalog"][data-kind="agent"]').click();
    const request = [...window.__PX_POSTED_MESSAGES__].reverse().find(message => message.type === 'loadStudioRevisionEditor' && message.kind === 'agent');
    const record = {
      agent_id: 'agent:preview-catalog', version: '1.0.0', project_id: 'project:preview', owner: 'human:owner',
      harness_id: 'harness:px', instructions: 'Authenticated base, not the retained overlay.', capability_binding_ids: ['binding:preview-agent'],
      effect_grant_ids: ['grant:preview-agent'], required_tests: ['identity', 'sandbox'], grants: [], bindings: [], lifecycle: 'admitted',
      lifecycle_authentication: { authenticated: true }, revision_sha256: '7'.repeat(64), source_content_sha256: '9'.repeat(64)
    };
    const selection = { kind: 'agent', catalog_kind: request.catalogKind, record_id: request.recordId, identity: record.agent_id, source_version: record.version, source_revision_sha256: record.revision_sha256, source_content_sha256: record.source_content_sha256, record };
    const allocation = { schema_version: 'px.studio-version-allocation/1.0', kind: 'agent', identity: record.agent_id, source_version: record.version, source_scope: 'studio-physical', source_revision_sha256: record.revision_sha256, source_content_sha256: record.source_content_sha256, candidate_version: '1.0.1', occupied_versions_sha256: '8'.repeat(64), observed_utc: '2026-08-16T00:00:00Z' };
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioRevisionEditorResult', requestId: request.requestId, kind: 'agent', catalogKind: request.catalogKind, recordId: request.recordId, selection, allocation, allocationProof: 'version-allocation:preview-mismatch-proof' } }));
  });
  await page.locator('[data-agent-root-field="instructions"]').waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => [...window.__PX_POSTED_MESSAGES__].some(message => message.type === 'releaseStudioTrust' && message.proof === 'version-allocation:preview-mismatch-proof')), true, 'a source-substituted response must release its unaccepted proof');
  assert.equal(await page.locator('[data-agent-root-field="instructions"]').inputValue(), 'Overlay must remain retained on mismatch.');
  assert.match(await page.locator('.studio-revision-baseline').allTextContents().then(values => values.join(' ')), /RETAINED OVERLAY RESTORED/);
  await page.keyboard.press('Escape');
  await page.locator('[data-action="openStudioDraft"][data-kind="agent"]').click();
  assert.match(await page.locator('.control-modal').textContent(), /agent:preview-catalog/);
});

test('U06 visual contract survives forced colors and 200%-equivalent reflow with retained screenshots', { timeout: 60000 }, async t => {
  fs.mkdirSync(visualEvidenceRoot, { recursive: true });
  const browser = await chromium.launch({ executablePath: browserLane.executablePath, headless: true });
  const context = await browser.newContext({
    viewport: { width: 720, height: 900 },
    deviceScaleFactor: 2,
    forcedColors: 'active',
    reducedMotion: 'reduce'
  });
  t.after(async () => { await browser.close(); });
  const page = await context.newPage();
  const failures = [];
  page.on('console', message => { if (message.type() === 'error') failures.push(`console: ${message.text()}`); });
  page.on('pageerror', error => failures.push(`page: ${error.message}`));

  await page.goto(`${preview}?surface=dashboard`); await settled(page);
  const hiddenSkipLink = await page.locator('.skip-link').boundingBox();
  assert.ok(hiddenSkipLink && hiddenSkipLink.x + hiddenSkipLink.width < 0, `unfocused skip link must be fully off canvas: ${JSON.stringify(hiddenSkipLink)}`);
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('skip-link')), true);
  const focusedSkipLink = await page.locator('.skip-link').boundingBox();
  assert.ok(focusedSkipLink && focusedSkipLink.x >= 0 && focusedSkipLink.y >= 0, `focused skip link must return to the viewport: ${JSON.stringify(focusedSkipLink)}`);
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'main-content');
  assert.equal(await page.evaluate(() => matchMedia('(forced-colors: active)').matches), true);
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
  assert.equal(await page.evaluate(() => devicePixelRatio), 2);
  await noHorizontalOverflow(page, 'dashboard-forced-colors-200pct');
  await assertContained(page, '.page-identity', '.cockpit-header', 'dashboard-forced-colors-page-identity');
  await assertContained(page, '.cockpit-actions', '.cockpit-header', 'dashboard-forced-colors-actions');
  assert.equal(await page.locator('.surface-dashboard .metric-grid').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length), 2);
  const metricCount = await page.locator('.surface-dashboard .metric-card').count();
  for (let index = 0; index < metricCount; index += 1) {
    await assertNoIntersection(page, `.surface-dashboard .metric-card:nth-child(${index + 1}) .metric-label`, `.surface-dashboard .metric-card:nth-child(${index + 1}) .inspect-cue`, `dashboard-metric-${index + 1}`);
  }
  if (await page.locator('.identity-warning[role="alert"]').count()) {
    await assertNoIntersection(page, '.identity-warning[role="alert"] > div:first-child > span', '.identity-warning[role="alert"] > div:first-child > strong', 'dashboard-identity-banner');
  }
  await page.locator('.nav-item').first().focus();
  const focus = await page.locator('.nav-item').first().evaluate(element => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), color: style.outlineColor };
  });
  assert.notEqual(focus.style, 'none', `forced-colors focus indicator missing: ${JSON.stringify(focus)}`);
  assert.ok(focus.width >= 2, `forced-colors focus indicator too thin: ${JSON.stringify(focus)}`);
  const dashboardShot = await page.screenshot({ path: path.join(visualEvidenceRoot, 'dashboard-forced-colors-200pct.png'), fullPage: true, animations: 'disabled' });
  assert.ok(dashboardShot.length > 10_000, 'dashboard visual evidence is unexpectedly empty');

  await page.goto(`${preview}?surface=knowledgeGraph`); await settled(page);
  await page.locator('.graph-node.actual').first().waitFor({ state: 'visible' });
  await noHorizontalOverflow(page, 'knowledge-graph-forced-colors-200pct');
  assert.ok(await page.locator('.graph-edge-group path').count() >= 10);
  const graphColors = await page.locator('.graph-edge-group path').first().evaluate(element => ({ stroke: getComputedStyle(element).stroke, forced: getComputedStyle(element).forcedColorAdjust }));
  assert.notEqual(graphColors.stroke, 'none', `forced-colors graph edge vanished: ${JSON.stringify(graphColors)}`);
  const compactRail = await page.locator('.control-rail').evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, labels: [...element.querySelectorAll('.nav-item span:not(.nav-icon)')].map(node => ({ text: node.textContent, display: getComputedStyle(node).display, width: node.getBoundingClientRect().width })) }));
  assert.ok(compactRail.labels.every(item => item.display === 'none' && item.width === 0), `compact rail painted hidden navigation labels: ${JSON.stringify(compactRail)}`);
  assert.ok(compactRail.scrollWidth <= compactRail.clientWidth + 1, `compact rail content escaped horizontally: ${JSON.stringify(compactRail)}`);
  await page.locator('[data-graph-canvas]').focus();
  const canvasOutline = await page.locator('[data-graph-canvas]').evaluate(element => parseFloat(getComputedStyle(element).outlineWidth));
  assert.ok(canvasOutline >= 2, `graph keyboard focus is not perceivable: ${canvasOutline}`);
  const graphShot = await page.screenshot({ path: path.join(visualEvidenceRoot, 'knowledge-graph-forced-colors-200pct.png'), fullPage: true, animations: 'disabled' });
  assert.ok(graphShot.length > 10_000, 'knowledge graph visual evidence is unexpectedly empty');
  assert.deepEqual(failures, []);
  writeVisualManifest(browser.version());
});
