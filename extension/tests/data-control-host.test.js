'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { PxBridge, captureJson } = require('../src/pxBridge');
const { descriptorFor, validatePayload, registerDataControlCommand } = require('../src/dataControlHost');
const { generateApprovalKey, canonicalJson } = require('../src/studioApprovalHost');

function fixture(t) {
  const parent = path.resolve(os.tmpdir());
  const root = fs.mkdtempSync(path.join(parent, 'px-data-control-host-'));
  t.after(() => {
    assert.equal(path.dirname(path.resolve(root)), parent);
    assert.ok(path.basename(root).startsWith('px-data-control-host-'));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const project = path.join(root, 'project');
  fs.mkdirSync(project);
  fs.mkdirSync(path.join(root, 'runtime'));
  fs.mkdirSync(path.join(root, 'registry'));
  fs.writeFileSync(path.join(root, 'runtime/dashboard_api.py'), '# source fixture');
  fs.writeFileSync(path.join(root, 'registry/tools.json'), '{"tools":[]}');
  fs.copyFileSync(path.resolve(__dirname, '../../runtime/data_control_contracts.json'), path.join(root, 'runtime/data_control_contracts.json'));
  const ring = { schema_version: 'px.studio-approval-keyring/2.0', active: generateApprovalKey(), previous: [] };
  const identity = 'px-project-fixture';
  const keys = path.join(root, 'host-keys');
  const descriptor = { schema_version: 'px.data-control-existing-host/1.0', project_identity: identity,
    key_root: keys, record_path: path.join(keys, 'approval-verifiers', `${identity}.json`), key_id: ring.active.keyId };
  const payload = { schema_version: 'px.personal-record-request/1.1', operation: 'personal-erase',
    requester_id: 'human:vscode-local-user', subject_id: 'explicit-subject', grant_id: 'explicit-existing-grant',
    policy_locator: '.agentic_engineering_os_px/runtime-core/data-controls/policy.json', idempotency_key: 'one-exact-erasure', purpose: 'rights-purpose' };
  return { root, project, ring, descriptor, payload };
}

test('existing host signs exact dedicated data scope and separate native transport', async t => {
  const f = fixture(t); const calls = [];
  const bridge = new PxBridge({ engineRoot: f.root, projectRoot: f.project, capture: async (_command, args, options) => {
    calls.push({ args, options });
    return args.includes('--describe-existing-approval') ? f.descriptor : { operation: 'personal-erase', affected_count: 1, coverage_complete: false };
  } });
  t.after(() => bridge.dispose());
  const approval = await bridge.issueDataControlApproval(f.payload, f.ring);
  const proof = approval.approval_capability;
  assert.equal(proof.claim.kind, 'data-controls');
  assert.equal(proof.claim.operation, 'personal-erase');
  assert.equal(proof.claim.payload_sha256, crypto.createHash('sha256').update(proof.payload_json).digest('hex'));
  assert.equal(crypto.verify('sha256', Buffer.from(canonicalJson(proof.claim)),
    { key: crypto.createPublicKey({ key: f.ring.active.publicKeyJwk, format: 'jwk' }), padding: crypto.constants.RSA_PKCS1_PADDING },
    Buffer.from(proof.signature, 'base64url')), true);
  const result = await bridge.dataControlOperation({ ...f.payload, approval_capability: proof });
  assert.equal(result.affected_count, 1);
  assert.deepEqual(calls[1].args, ['-m', 'runtime.data_controls', '--project-root', f.project]);
  assert.equal(calls[1].options.cwd, f.root);
  assert.equal(calls[1].options.maxOutputBytes, 4 * 1024 * 1024);
  assert.equal(calls[1].options.sensitiveResponse, true);
  assert.deepEqual(JSON.parse(calls[1].options.input), { ...f.payload, approval_capability: proof });
  await assert.rejects(bridge.studioOperation('data-controls', 'personal-erase', f.payload), /Unsupported studio kind/);
  await assert.rejects(bridge.dataControlOperation({ ...f.payload, subject_id: 'substituted', approval_capability: proof }), /exact payload/);
});

test('uncommissioned or wrong-boundary host identities cannot sign', async t => {
  const f = fixture(t);
  const bridge = new PxBridge({ engineRoot: f.root, projectRoot: f.project, capture: async () => ({ ...f.descriptor, key_root: f.project, record_path: path.join(f.project, 'approval-verifiers/px-project-fixture.json') }) });
  t.after(() => bridge.dispose());
  await assert.rejects(bridge.issueDataControlApproval(f.payload, null), /Existing host signing/);
  await assert.rejects(bridge.issueDataControlApproval(f.payload, f.ring), /boundary differs/);
  const noProject = new PxBridge({ engineRoot: f.root });
  t.after(() => noProject.dispose());
  await assert.rejects(noProject.issueDataControlApproval(f.payload, f.ring), /explicit engine\/project/);
});

test('closed native descriptor and payload reject browser authority and unsupported effects', t => {
  const f = fixture(t); const descriptor = descriptorFor(f.root);
  assert.equal(Object.values(descriptor.owners).flatMap(row => row.operations).length, 12);
  assert.throws(() => validatePayload(descriptor, { ...f.payload, approval_capability: {} }), /fields/);
  assert.throws(() => validatePayload(descriptor, { ...f.payload, requester_id: 'browser:invented' }), /actor/);
  assert.throws(() => validatePayload(descriptor, { ...f.payload, operation: 'arbitrary-delete' }), /Unsupported/);
  assert.throws(() => validatePayload(descriptor, { ...f.payload, policy_locator: '../arbitrary.json' }), /Canonical/);
});

test('normal command requires manual exact confirmation then displays an unsaved result', async t => {
  const f = fixture(t); const locator = path.join(f.root, 'request.json'); fs.writeFileSync(locator, JSON.stringify(f.payload));
  const seen = []; let command; let secretsRead = 0;
  const bridge = { engineRoot: f.root, projectRoot: f.project,
    async issueDataControlApproval(payload, ring) { seen.push(['approval', payload, ring]); return { approval_capability: { opaque: 'host proof' } }; },
    async dataControlOperation(payload) { seen.push(['operation', payload]); return { affected_count: 1, residual_surfaces: ['sealed history'], coverage_complete: false }; } };
  const vscode = {
    commands: { registerCommand(id, handler) { assert.equal(id, 'pacifyX.manageSubjectData'); command = handler; return { dispose() {} }; } },
    window: { async showQuickPick() { return 'personal-erase'; }, async showOpenDialog() { return [{ fsPath: locator }]; },
      async showWarningMessage(_message, options, button) { seen.push(['confirmation', options]); assert.equal(options.modal, true); return button; },
      async showTextDocument(document) { seen.push(['display', document]); } },
    workspace: { async openTextDocument(options) { seen.push(['document', options]); return options; } }
  };
  registerDataControlCommand(vscode, { secrets: { async get() { secretsRead++; return JSON.stringify(f.ring); } } }, () => bridge);
  const result = await command({ approval_capability: 'ignored injected command argument' });
  assert.equal(secretsRead, 1);
  assert.deepEqual(seen.slice(0, 3).map(row => row[0]), ['confirmation', 'approval', 'operation']);
  assert.match(seen[0][1].detail, /provider copies, external backups/);
  assert.equal(seen[3][1].language, 'json');
  assert.equal(result.coverage_complete, false);
  assert.equal(fs.readFileSync(locator, 'utf8'), JSON.stringify(f.payload));
});

test('cancelled confirmation and changed project never sign or execute', async t => {
  const f = fixture(t); const locator = path.join(f.root, 'request.json'); fs.writeFileSync(locator, JSON.stringify(f.payload));
  let command; let authorize = false;
  const bridge = { engineRoot: f.root, projectRoot: f.project, issueDataControlApproval() { assert.fail('must not sign'); } };
  const vscode = { commands: { registerCommand(_id, handler) { command = handler; } },
    window: { async showQuickPick() { return 'personal-erase'; }, async showOpenDialog() { return [{ fsPath: locator }]; },
      async showWarningMessage() { if (authorize) bridge.projectRoot = f.root; return authorize ? 'Authorize exact request' : undefined; } } };
  registerDataControlCommand(vscode, { secrets: { get() { assert.fail('must not read signing key'); } } }, () => bridge);
  assert.equal((await command()).status, 'cancelled');
  authorize = true;
  await assert.rejects(command(), /project changed/);
});

test('bounded sensitive capture never reveals stderr or malformed response content', async t => {
  const cp = require('node:child_process');
  const { EventEmitter } = require('node:events');
  const { PassThrough } = require('node:stream');
  let scenario = 'stderr';
  t.mock.method(cp, 'spawn', () => {
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => true;
    process.nextTick(() => {
      if (scenario === 'stderr') { child.stderr.write('private-subject-content'); child.emit('close', 1); }
      else { child.stdout.write('private-subject-content'); child.emit('close', 0); }
    });
    return child;
  });
  await assert.rejects(captureJson('not-executed', [], { sensitiveResponse: true, maxOutputBytes: 128 }), error =>
    /rejected the request/.test(error.message) && !error.message.includes('private-subject-content'));
  scenario = 'malformed';
  await assert.rejects(captureJson('not-executed', [], { sensitiveResponse: true, maxOutputBytes: 128 }), error =>
    /invalid bounded JSON/.test(error.message) && !error.message.includes('private-subject-content'));
  await assert.rejects(captureJson('not-executed', [], { maxOutputBytes: 0 }), /Invalid native output bound/);
});

test('purpose and expected generation bind all new native rights/control operations', t => {
  const f = fixture(t); const descriptor = descriptorFor(f.root);
  const base = { ...f.payload }; delete base.idempotency_key;
  validatePayload(descriptor, { ...base, operation: 'personal-use' });
  const rectify = { ...base, operation: 'personal-rectify', idempotency_key: 'rectification', record_id: 'record-one',
    expected_generation: 3, replacement_content: { name: 'corrected' } };
  validatePayload(descriptor, rectify);
  validatePayload(descriptor, { ...base, operation: 'personal-withdraw-consent', idempotency_key: 'withdrawal',
    expected_generation: 3, consent_reference: 'explicit-existing-consent' });
  assert.throws(() => validatePayload(descriptor, { ...rectify, expected_generation: true }), /generation/);
  const noPurpose = { ...base, operation: 'personal-use' }; delete noPurpose.purpose;
  assert.throws(() => validatePayload(descriptor, noPurpose), /fields/);
});
