'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const { collectStudioCatalog } = require('../src/studioCatalog');

function loadStudioEditors() {
  const context = vm.createContext({});
  context.globalThis = context;
  for (const file of ['00-foundation.js', '49-studio-editors.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', file), 'utf8'), context, { filename: file });
  }
  return context.PXDashboard.require('studioEditors');
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function digest(value) {
  return crypto.createHash('sha256').update(Buffer.from(canonicalJson(value), 'utf8')).digest('hex');
}

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])]));
  return value;
}

function write(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(sorted(value), null, 2)}\n`, 'utf8');
}

function fixture(t, { modern = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-workflow-layout-catalog-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const revision = path.join(
    root, '.engineering-bootstrap', 'studios', 'workflows',
    'workflow-layout-demo-deadbeef', 'revisions', '1.0.0'
  );
  fs.mkdirSync(revision, { recursive: true });
  const workflow = {
    workflow_id: 'workflow:layout-demo',
    version: '1.0.0',
    owner: 'human:owner',
    nodes: [
      {
        node_id: 'node:first', executor_binding_id: 'binding:first',
        inputs: [{ name: 'value', data_type: 'string', required: true }],
        outputs: [{ name: 'value', data_type: 'string', required: true }],
        effect_grant_ids: ['grant:first'], failure_policy: 'fail-closed',
        timeout_seconds: 5, retry_limit: 0, approval_required: false,
        kind: 'task', config: {}
      },
      {
        node_id: 'node:second', executor_binding_id: 'binding:second',
        inputs: [{ name: 'value', data_type: 'string', required: true }],
        outputs: [{ name: 'value', data_type: 'string', required: true }],
        effect_grant_ids: ['grant:second'], failure_policy: 'fail-closed',
        timeout_seconds: 5, retry_limit: 0, approval_required: false,
        kind: 'task', config: {}
      }
    ],
    edges: [{ source_node: 'node:first', source_port: 'value', target_node: 'node:second', target_port: 'value', condition: 'always' }],
    lifecycle: 'draft'
  };
  const recordFile = path.join(revision, 'record.json');
  const recordEnvelope = {
    schema_version: 'px.workflowdefinition/1.0',
    record: workflow,
    sha256: digest(workflow)
  };
  write(recordFile, recordEnvelope);
  const recordSha256 = crypto.createHash('sha256').update(fs.readFileSync(recordFile)).digest('hex');
  const layout = { 'node:first': { x: 0, y: -125.5 }, 'node:second': { x: 420.25, y: 0 } };
  const layoutEnvelope = {
    schema_version: 'px.workflow-editor-layout/1.0',
    workflow_id: workflow.workflow_id,
    version: workflow.version,
    revision_sha256: recordSha256,
    layout,
    layout_sha256: digest(layout)
  };
  const grants = ['first', 'second'].map(name => ({ grant_id: `grant:${name}`, subject_id: workflow.workflow_id, effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: [`receipt:grant-${name}`], expires_utc: null, state: 'admitted' }));
  const bindings = ['first', 'second'].map(name => ({ binding_id: `binding:${name}`, subject_kind: 'workflow', subject_id: workflow.workflow_id, capability_id: `capability:${name}`, capability_version: '1.0.0', effect_grant_ids: [`grant:${name}`], credential_namespace: null, cost_policy: `bounded-${name}`, egress_policy: name === 'first' ? 'deny' : 'loopback-only', state: 'admitted', evidence_refs: [`receipt:binding-${name}`] }));
  const authority = {
    schema_version: 'px.studio-authority-definition/1.0', kind: 'workflow', subject_id: workflow.workflow_id, version: workflow.version, builder_domain: 'px-standard',
    bindings, grants, executor_adapters: { 'binding:first': 'identity', 'binding:second': 'fail' },
    run_input_contract: [{ key: 'node:first.value', value_type: 'string', required: true }], runtime_input_values_stored: false
  };
  const authorityEnvelope = { record: authority, sha256: digest(authority) };
  const files = {
    record: recordFile,
    layout: path.join(revision, 'editor-layout.json'),
    authority: path.join(revision, 'authority-definition.json'),
    creation: path.join(revision, 'creation-receipt.json')
  };
  if (modern) {
    write(files.layout, layoutEnvelope);
    write(files.authority, authorityEnvelope);
    write(files.creation, {
      schema_version: 'px.workflow-revision-receipt/1.2',
      operation: 'workflow.save_revision',
      created_utc: '2026-08-16T00:00:00.000Z',
      workflow_id: workflow.workflow_id,
      version: workflow.version,
      revision_sha256: recordSha256,
      definition_sha256: recordEnvelope.sha256,
      definition_state: 'saved',
      runnable_state: 'unvalidated',
      run_state: 'never_run',
      path: path.relative(root, files.record).replaceAll('\\', '/'),
      created: true,
      authority_state: 'defined',
      authority_definition_path: path.relative(root, files.authority).replaceAll('\\', '/'),
      editor_layout_state: 'content-bound',
      editor_layout_path: path.relative(root, files.layout).replaceAll('\\', '/'),
      editor_layout_sha256: layoutEnvelope.layout_sha256,
      host_authority_retained: true
    });
  }
  return { root, workflow, recordEnvelope, recordSha256, layout, layoutEnvelope, authority, authorityEnvelope, files };
}

function snapshot(directory) {
  return Object.fromEntries(fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).map(entry => [
    entry.name,
    entry.isDirectory() ? snapshot(path.join(directory, entry.name)) : fs.readFileSync(path.join(directory, entry.name), 'base64')
  ]));
}

test('workflow catalog reopens exact content-bound layout and exposes both hashes', t => {
  const data = fixture(t);
  const page = collectStudioCatalog(data.root, 'workflows');
  assert.equal(page.refused, 0);
  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].details.revision_sha256, data.recordSha256);
  assert.equal(page.items[0].details.definition_sha256, data.recordEnvelope.sha256);
  assert.equal(page.items[0].details.editor_layout_state, 'content-bound');
  assert.deepEqual(page.items[0].details.editor_layout, data.layout);
  assert.deepEqual(page.items[0].details.bindings, data.authority.bindings);
  assert.deepEqual(page.items[0].details.grants, data.authority.grants);
  assert.deepEqual(page.items[0].details.executor_adapters, data.authority.executor_adapters);
  assert.deepEqual(page.items[0].details.run_input_contract, data.authority.run_input_contract);
  assert.equal(page.items[0].details.authority_definition_state, 'stored-with-revision');
  assert.equal(page.items[0].details.runtime_input_values_state, 'not-stored-by-design');
  const reopened = loadStudioEditors().normalizeWorkflow(page.items[0].details);
  assert.deepEqual(JSON.parse(JSON.stringify(reopened.editor_layout)), data.layout);
  assert.deepEqual(Object.fromEntries(reopened.nodes.map(node => [node.node_id, JSON.parse(JSON.stringify(node.position))])), data.layout);
});

test('workflow catalog refuses changed, incomplete, and wrong-node modern layouts', t => {
  const changed = fixture(t);
  changed.layoutEnvelope.layout['node:first'].x = 1;
  write(changed.files.layout, changed.layoutEnvelope);
  let page = collectStudioCatalog(changed.root, 'workflows');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);

  const missing = fixture(t);
  fs.unlinkSync(missing.files.layout);
  page = collectStudioCatalog(missing.root, 'workflows');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);

  const wrongNode = fixture(t);
  wrongNode.layoutEnvelope.layout = { 'node:first': { x: 0, y: 0 } };
  wrongNode.layoutEnvelope.layout_sha256 = digest(wrongNode.layoutEnvelope.layout);
  write(wrongNode.files.layout, wrongNode.layoutEnvelope);
  page = collectStudioCatalog(wrongNode.root, 'workflows');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);

  const malformedAuthority = fixture(t);
  malformedAuthority.authorityEnvelope.record.runtime_input_values_stored = true;
  malformedAuthority.authorityEnvelope.sha256 = digest(malformedAuthority.authorityEnvelope.record);
  write(malformedAuthority.files.authority, malformedAuthority.authorityEnvelope);
  page = collectStudioCatalog(malformedAuthority.root, 'workflows');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);
});

test('workflow catalog labels legacy layout unavailable without backfill', t => {
  const data = fixture(t, { modern: false });
  write(data.files.creation, { schema_version: 'px.workflow-revision-receipt/1.1' });
  const before = snapshot(data.root);
  const page = collectStudioCatalog(data.root, 'workflows');
  assert.equal(page.refused, 0);
  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].details.editor_layout_state, 'legacy-unavailable');
  assert.equal(page.items[0].details.editor_layout, undefined);
  assert.deepEqual(snapshot(data.root), before);
});
