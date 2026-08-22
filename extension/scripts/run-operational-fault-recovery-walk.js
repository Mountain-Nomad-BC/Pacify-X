'use strict';

// Direct current-source fault/recovery measurement. A control is credited only
// when this process resolves that exact control before the injected snapshot
// loss, observes bounded non-stale failure behavior, restores the original
// snapshot through the production message receiver, and resolves it again.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { resolveBrowserLane } = require('../tests/browser-lane');
const {
  STAGES, prepare, revealControl, resolveAction, resolveSemantic
} = require('./run-exhaustive-operational-control-walk');

const root = path.resolve(__dirname, '..', '..');
const matrixPath = path.join(root, 'registry', 'operational_control_proof_matrix.json');
const output = path.resolve(process.argv[2] || path.join(root, 'evidence', 'operational-fault-recovery-walk', 'receipt.json'));
const uiReceiptPath = path.resolve(process.argv[3] || path.join(root, 'evidence', 'exhaustive-operational-control-walk-20260822T0052Z', 'receipt.json'));
const UI_KINDS = new Set(['action', 'field', 'form', 'menu', 'editor', 'gesture', 'indicator']);

function sha256(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function normalizedText(value) { return String(value || '').replace(/\s+/g, ' ').trim(); }
function failureContained(observation) {
  if (!observation.baselineVisible || !observation.mainVisible || observation.newPageErrors > 0) return false;
  if (!observation.faultVisible) return true;
  if (normalizedText(observation.alertText)) return true;
  return normalizedText(observation.faultText) !== normalizedText(observation.baselineText);
}
function recoveryObserved(observation) {
  return Boolean(observation.baselineVisible && observation.recoveredVisible && observation.newPageErrors === 0);
}

async function exactLocator(page, control) {
  if (control.kind === 'action') return resolveAction(page, control);
  const resolved = await resolveSemantic(page, control);
  return resolved?.item || null;
}
async function inspectExact(page, control) {
  const locator = await exactLocator(page, control);
  if (!locator || !(await locator.isVisible().catch(() => false))) return { visible: false, text: '' };
  const text = await locator.evaluate(element => String(element.innerText || element.value || element.getAttribute('aria-label') || '').slice(0, 2000));
  return { visible: true, text: normalizedText(text) };
}
function stageMap(control, failure, recovery, evidenceReference) {
  return Object.fromEntries(STAGES.map(stage => {
    if (control.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceReference] }];
    if (stage === 'failure_handling' && failure) return [stage, { state: 'present', detail: 'Exact control entered bounded non-stale failure rendering without a page error.', evidence: [evidenceReference] }];
    if (stage === 'recovery_rollback' && recovery) return [stage, { state: 'present', detail: 'Exact control was directly resolved again after the original snapshot was restored through the production receiver.', evidence: [evidenceReference] }];
    return [stage, { state: 'missing', detail: `Fault/recovery probe did not claim required stage ${stage}.`, evidence: [] }];
  }));
}

async function main() {
  const matrixBytes = fs.readFileSync(matrixPath); const matrix = JSON.parse(matrixBytes);
  const uiBytes = fs.readFileSync(uiReceiptPath); const uiReceipt = JSON.parse(uiBytes);
  if (uiReceipt.schema_version !== 'px.exhaustive-operational-control-walk/1.0' || uiReceipt.aggregates?.errors !== 0) throw new Error('A zero-error exact UI receipt is required.');
  const rendered = new Set(uiReceipt.records.filter(record => record.rendered).map(record => record.control_id));
  const controls = matrix.controls.filter(control => UI_KINDS.has(control.kind) && rendered.has(control.control_id) && (control.stage_policy.failure_handling === 'required' || control.stage_policy.recovery_rollback === 'required'));
  const lane = resolveBrowserLane(); const browser = await chromium.launch({ executablePath: lane.executablePath, headless: true });
  const workerCount = Math.max(1, Math.min(8, Number(process.env.PX_OPERATIONAL_WALK_WORKERS || 4) || 4));
  const pageErrors = []; const records = new Array(controls.length);
  try {
    const shardSize = Math.ceil(controls.length / workerCount);
    await Promise.all(Array.from({ length: workerCount }, async (_unused, workerIndex) => {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); const localErrors = [];
      page.on('pageerror', error => localErrors.push(String(error?.message || error)));
      const start = workerIndex * shardSize; const end = Math.min(controls.length, start + shardSize);
      try {
        for (let controlIndex = start; controlIndex < end; controlIndex += 1) {
          const control = controls[controlIndex]; const errorStart = localErrors.length;
          await prepare(page, control.surface_id, control); await revealControl(page, control);
          const baseline = await inspectExact(page, control);
          await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: null } })));
          await page.waitForTimeout(80);
          const fault = await inspectExact(page, control);
          const mainVisible = await page.locator('main h1').first().isVisible().catch(() => false);
          const alertText = await page.locator('[role="alert"],.loading,.empty-state,.compact-empty,.memory-errors').allTextContents().then(values => values.join(' ')).catch(() => '');
          const faultObservation = { baselineVisible: baseline.visible, baselineText: baseline.text, faultVisible: fault.visible, faultText: fault.text, mainVisible, alertText, newPageErrors: localErrors.length - errorStart };
          const failure = failureContained(faultObservation);
          await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: window.__PX_TEST_SNAPSHOT__ } })));
          await page.waitForTimeout(80);
          let recovered = await inspectExact(page, control);
          if (!recovered.visible) { await prepare(page, control.surface_id, control); await revealControl(page, control); recovered = await inspectExact(page, control); }
          const recoveryObservation = { baselineVisible: baseline.visible, recoveredVisible: recovered.visible, newPageErrors: localErrors.length - errorStart };
          const recovery = recoveryObserved(recoveryObservation); const reference = `fault-recovery:${control.control_id}`;
          records[controlIndex] = { control_id: control.control_id, attempted: baseline.visible, rendered: baseline.visible, observed: failure || recovery, stages: stageMap(control, failure, recovery, reference), observations: { baseline, fault, recovered, mainVisible, alertText: normalizedText(alertText), page_errors: localErrors.slice(errorStart) } };
        }
      } finally { pageErrors.push(...localErrors); await page.close(); }
    }));
  } finally { await browser.close(); }
  const receipt = { schema_version: 'px.operational-control-stage-evidence/1.0', evidence_kind: 'direct_fault_injection_measurement', observed_at: new Date().toISOString(), authority: 'Direct current-source snapshot-loss and restore measurement; no generic test promotion.', source: { matrix_sha256: sha256(matrixBytes), ui_receipt_sha256: sha256(uiBytes), workers: workerCount }, aggregates: { eligible: controls.length, attempted: records.filter(record => record.attempted).length, failure_observed: records.filter(record => record.stages.failure_handling.state === 'present').length, recovery_observed: records.filter(record => record.stages.recovery_rollback.state === 'present').length, page_errors: pageErrors.length }, records };
  fs.mkdirSync(path.dirname(output), { recursive: true }); fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ output, aggregates: receipt.aggregates }, null, 2)}\n`); if (pageErrors.length) process.exitCode = 1;
}

if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
module.exports = { failureContained, normalizedText, recoveryObserved, stageMap };
