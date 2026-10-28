'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { KEYRING_SECRET, validMaterial } = require('./studioApprovalHost');

const MAX_REQUEST_BYTES = 256 * 1024;
const EXPECTED = Object.freeze({
  'runtime.data_subject_records': ['subject-access', 'subject-export', 'subject-erase', 'subject-retention'],
  'runtime.personal_record_store': ['personal-create', 'personal-access', 'personal-export', 'personal-erase', 'personal-retention', 'personal-use', 'personal-rectify', 'personal-withdraw-consent']
});

function descriptorFor(engineRoot) {
  const locator = path.join(engineRoot, 'runtime', 'data_control_contracts.json');
  const stat = fs.lstatSync(locator);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 64 * 1024) throw new Error('Data control descriptor unavailable.');
  const descriptor = JSON.parse(fs.readFileSync(locator, 'utf8'));
  if (descriptor.schema_version !== 'px.data-control-owner-contract/1.0' ||
      Object.keys(descriptor.owners || {}).sort().join('|') !== Object.keys(EXPECTED).sort().join('|')) throw new Error('Data control descriptor differs.');
  for (const [owner, operations] of Object.entries(EXPECTED)) {
    const declared = descriptor.owners[owner]?.operations;
    if (!Array.isArray(declared) || declared.length !== operations.length ||
        [...declared].sort().join('|') !== [...operations].sort().join('|')) throw new Error('Data control approval scope differs.');
  }
  return descriptor;
}

function validatePayload(descriptor, payload) {
  if (!payload || Object.getPrototypeOf(payload) !== Object.prototype) throw new Error('Data control request must be a closed object.');
  const entry = Object.values(descriptor.owners).find(row => row.operations.includes(payload.operation));
  if (!entry || payload.schema_version !== entry.schema_version) throw new Error('Unsupported native data control scope.');
  const fields = ['schema_version', 'operation', 'requester_id', 'subject_id', 'grant_id', 'policy_locator'];
  if (payload.operation.startsWith('subject-')) fields.push('binding_locator');
  if (payload.operation.startsWith('personal-')) fields.push('purpose');
  if (['personal-create', 'personal-erase', 'personal-retention', 'personal-rectify', 'personal-withdraw-consent'].includes(payload.operation)) fields.push('idempotency_key');
  if (payload.operation === 'personal-create') fields.push('record');
  if (payload.operation === 'personal-rectify') fields.push('record_id', 'expected_generation', 'replacement_content');
  if (payload.operation === 'personal-withdraw-consent') fields.push('consent_reference', 'expected_generation');
  if (Object.keys(payload).sort().join('|') !== fields.sort().join('|') ||
      fields.filter(field => !['record', 'expected_generation', 'replacement_content'].includes(field)).some(field => typeof payload[field] !== 'string' || !payload[field] || Buffer.byteLength(payload[field]) > 512) ||
      payload.requester_id !== 'human:vscode-local-user') throw new Error('Data control request fields or authenticated actor differ.');
  if (fields.includes('expected_generation') && (!Number.isSafeInteger(payload.expected_generation) || payload.expected_generation < 0 || payload.expected_generation > 1_000_000_000)) throw new Error('Exact expected generation required.');
  for (const key of ['policy_locator', 'binding_locator'].filter(key => fields.includes(key))) {
    const value = payload[key];
    if (!value.startsWith('.agentic_engineering_os_px/runtime-core/data-controls/') || value.includes('\\') ||
        value.split('/').some(part => !part || part === '.' || part === '..')) throw new Error('Canonical data control locator required.');
  }
  const image = Buffer.from(JSON.stringify(payload), 'utf8');
  if (image.length > MAX_REQUEST_BYTES) throw new Error('Data control request exceeds its bound.');
  return payload;
}

function readRequestFile(locator) {
  const stat = fs.lstatSync(locator);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_REQUEST_BYTES) throw new Error('Bounded regular data-control request file required.');
  const image = fs.readFileSync(locator);
  if (image.length > MAX_REQUEST_BYTES) throw new Error('Data control request exceeds its bound.');
  const text = image.toString('utf8');
  if (!Buffer.from(text, 'utf8').equals(image)) throw new Error('Data control request must be valid UTF-8.');
  try { return JSON.parse(text); }
  catch { throw new Error('Data control request must be valid bounded JSON.'); }
}

function registerDataControlCommand(vscode, context, getBridge) {
  return vscode.commands.registerCommand('pacifyX.manageSubjectData', async () => {
    const bridge = getBridge();
    if (!bridge?.projectRoot || !bridge?.engineRoot) throw new Error('Explicit project and engine roots are required.');
    const root = path.resolve(bridge.projectRoot);
    const engine = path.resolve(bridge.engineRoot);
    const descriptor = descriptorFor(engine);
    const selected = await vscode.window.showQuickPick(Object.values(EXPECTED).flat(), { title: 'PX subject data controls', placeHolder: 'Choose an explicitly approved native operation' });
    if (!selected) return { status: 'cancelled' };
    const files = await vscode.window.showOpenDialog({ canSelectMany: false, canSelectFiles: true, canSelectFolders: false,
      openLabel: 'Review data-control request', filters: { 'Data-control JSON request': ['json'] } });
    if (!files?.length) return { status: 'cancelled' };
    const payload = validatePayload(descriptor, readRequestFile(files[0].fsPath));
    if (payload.operation !== selected) throw new Error('Selected operation differs from the exact request.');
    const detail = [`Project: ${root}`, `Subject: ${payload.subject_id}`, `Operation: ${payload.operation}`,
      `Policy: ${payload.policy_locator}`, `Grant: ${payload.grant_id}`,
      payload.purpose ? `Requested purpose: ${payload.purpose}` : '',
      payload.expected_generation != null ? `Expected current generation: ${payload.expected_generation}` : '',
      payload.consent_reference ? `Consent reference to withdraw: ${payload.consent_reference}; operational use will be blocked, live content retained pending approved erasure.` : '',
      payload.record_id ? `Record to rectify: ${payload.record_id}; no erased identity can be recreated.` : '',
      payload.record ? `Purpose: ${payload.record.purpose}; consent reference: ${payload.record.consent_reference}; record: ${payload.record.record_id}` : '',
      'The native policy/grant must already be approved. Sealed MemoryVault/T.I.E., provider copies, external backups, original request files, unsaved response documents and OS remnants are not erased. No legal compliance is asserted.'].filter(Boolean).join('\n');
    const confirmation = await vscode.window.showWarningMessage('Authorize this exact PX subject-data request?', { modal: true, detail }, 'Authorize exact request');
    if (confirmation !== 'Authorize exact request') return { status: 'cancelled' };
    if (getBridge() !== bridge || path.resolve(bridge.projectRoot) !== root || path.resolve(bridge.engineRoot) !== engine) throw new Error('Data control project changed during confirmation.');
    const rawKeyring = await context.secrets.get(KEYRING_SECRET);
    if (!rawKeyring || Buffer.byteLength(rawKeyring) > 128 * 1024) throw new Error('Existing host approval signing identity is required; commission it explicitly first.');
    let ring;
    try { ring = JSON.parse(rawKeyring); }
    catch { throw new Error('Existing host approval signing identity is invalid.'); }
    if (ring.schema_version !== 'px.studio-approval-keyring/2.0' || !validMaterial(ring.active)) throw new Error('Existing host approval signing identity is invalid.');
    const approval = await bridge.issueDataControlApproval(payload, ring);
    const result = await bridge.dataControlOperation({ ...payload, approval_capability: approval.approval_capability });
    if (Buffer.byteLength(JSON.stringify(result)) > 4 * 1024 * 1024) throw new Error('Data control response exceeds its bound.');
    // VS Code owns this unsaved result document. No private response is logged,
    // cached as webview state, or written to an arbitrary export path.
    const document = await vscode.workspace.openTextDocument({ language: 'json', content: JSON.stringify(result, null, 2) });
    await vscode.window.showTextDocument(document, { preview: true });
    return { status: 'response-displayed', operation: payload.operation, coverage_complete: false };
  });
}

module.exports = { descriptorFor, validatePayload, readRequestFile, registerDataControlCommand, EXPECTED, MAX_REQUEST_BYTES };
