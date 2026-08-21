'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { setupStudio, STARTER_AGENT, STARTER_WORKFLOW } = require('../src/studioBootstrap');
const { PxBridge, exactStudioVersionConflictError } = require('../src/pxBridge');
const { generateApprovalKey } = require('../src/studioApprovalHost');
const { createStudioDraftFromHost } = require('../src/studioDraftHost');
const { materializeSkillPackage, reclaimMaterializedSkillPackage } = require('../src/studioPackage');

test('Studio setup creates, admits, and runs editable starter agent and workflow revisions', async () => {
  const calls = [];
  const bridge = {
    async issueStudioApproval(kind, operation, payload) {
      calls.push(['approve', kind, operation, payload]);
      return { approval_capability: { exact: `${kind}:${operation}` } };
    },
    async studioOperation(kind, operation, payload) {
      calls.push(['operate', kind, operation, payload]);
      if (kind === 'agent' && operation === 'test') return { passed: true };
      if (operation === 'admit' || (kind === 'workflow' && operation === 'validate')) return { decision: 'admitted' };
      if (kind === 'agent' && operation === 'run') return { run_id: 'run:agent-starter', run_outcome: 'succeeded' };
      if (kind === 'workflow' && operation === 'dry-run') return { effects_executed: false, runnable: true };
      if (kind === 'workflow' && operation === 'run') return { run_id: 'run:workflow-starter', run_state: 'succeeded' };
      return { created: true };
    }
  };
  const progress = [];
  const result = await setupStudio(bridge, { progress: value => progress.push(value) });
  assert.equal(result.ready, true);
  assert.equal(result.agent.decision, 'admitted');
  assert.equal(result.workflow.decision, 'admitted');
  assert.equal(result.completed_steps.length, 10);
  assert.deepEqual(progress, result.completed_steps);
  assert.equal(calls.filter(call => call[0] === 'approve').length, 9, 'dry-run is the sole unsigned read-only operation');
  assert.equal(calls.filter(call => call[0] === 'operate').length, 10);
  assert.equal(STARTER_AGENT.agent_id, 'agent:pacify-x-starter');
  assert.equal(STARTER_WORKFLOW.workflow_id, 'workflow:pacify-x-starter');
});

test('Studio setup stops immediately when agent admission is not admitted', async () => {
  const operations = [];
  const bridge = {
    async issueStudioApproval() { return { approval_capability: { exact: true } }; },
    async studioOperation(kind, operation) {
      operations.push(`${kind}:${operation}`);
      if (operation === 'test') return { passed: true };
      if (operation === 'admit') return { decision: 'blocked' };
      return { created: true };
    }
  };
  await assert.rejects(setupStudio(bridge), /agent-admission-failed/);
  assert.equal(operations.includes('agent:run'), false);
  assert.equal(operations.some(value => value.startsWith('workflow:')), false);
});

test('Studio setup crosses the real host-to-Python boundary and leaves reopenable runnable revisions', { timeout: 120000 }, async t => {
  const engineRoot = path.resolve(__dirname, '..', '..');
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-product-project-'));
  const keyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-product-keys-'));
  const previousKeyRoot = process.env.PX_STUDIO_KEY_ROOT;
  process.env.PX_STUDIO_KEY_ROOT = keyRoot;
  const bridge = new PxBridge({
    engineRoot,
    projectRoot,
    approvalKeyProvider: async request => request?.action === 'find' ? null : { active: generateApprovalKey(), previous: [] }
  });
  t.after(() => {
    bridge.dispose();
    if (previousKeyRoot === undefined) delete process.env.PX_STUDIO_KEY_ROOT;
    else process.env.PX_STUDIO_KEY_ROOT = previousKeyRoot;
    fs.rmSync(projectRoot, { recursive: true, force: true });
    fs.rmSync(keyRoot, { recursive: true, force: true });
  });

  // Retain one stable host signing identity for the complete lifecycle.
  const material = generateApprovalKey();
  bridge.approvalKeyProvider = async request => request?.action === 'find' && request.keyId !== material.keyId
    ? null
    : request?.action === 'find' ? material : { active: material, previous: [] };

  const result = await setupStudio(bridge);
  assert.equal(result.ready, true);
  assert.equal(result.agent.run_outcome, 'succeeded');
  assert.equal(result.workflow.run_state, 'succeeded');

  const agents = await bridge.catalog({ kind: 'agents', query: STARTER_AGENT.agent_id, status: '', offset: 0, limit: 20, sort: 'id' });
  const workflows = await bridge.catalog({ kind: 'workflows', query: STARTER_WORKFLOW.workflow_id, status: '', offset: 0, limit: 20, sort: 'id' });
  const agent = agents.items.find(item => item.kind === 'studio-agent-revision' && item.details?.agent_id === STARTER_AGENT.agent_id);
  const workflow = workflows.items.find(item => item.kind === 'studio-workflow-revision' && item.details?.workflow_id === STARTER_WORKFLOW.workflow_id);
  assert.equal(agent?.details?.lifecycle_authentication?.authenticated, true);
  assert.equal(agent?.details?.builder_graph_state, 'content-bound');
  assert.equal(workflow?.details?.lifecycle_authentication?.authenticated, true);
  assert.equal(workflow?.details?.editor_layout_state, 'content-bound');
});

test('Skill Studio editor files cross the real host boundary and reopen as an editable project revision', { timeout: 120000 }, async t => {
  const engineRoot = path.resolve(__dirname, '..', '..');
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-studio-project-'));
  const keyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-studio-keys-'));
  const previousKeyRoot = process.env.PX_STUDIO_KEY_ROOT;
  process.env.PX_STUDIO_KEY_ROOT = keyRoot;
  const material = generateApprovalKey();
  const bridge = new PxBridge({
    engineRoot,
    projectRoot,
    approvalKeyProvider: async request => request?.action === 'find' && request.keyId !== material.keyId
      ? null
      : request?.action === 'find' ? material : { active: material, previous: [] }
  });
  t.after(() => {
    bridge.dispose();
    if (previousKeyRoot === undefined) delete process.env.PX_STUDIO_KEY_ROOT;
    else process.env.PX_STUDIO_KEY_ROOT = previousKeyRoot;
    fs.rmSync(projectRoot, { recursive: true, force: true });
    fs.rmSync(keyRoot, { recursive: true, force: true });
  });

  const skillId = 'skill:host-bound-editor';
  const version = '1.0.0';
  const editorFiles = {
    'SKILL.md': `---\nname: ${skillId}\ndescription: Prove the editable Skill Studio package round trip.\n---\n\n# Host-bound editor\n`,
    'capability.json': `${JSON.stringify({ schema_version: 'px.skill-capability/1.0', id: skillId, version, domain: 'px-standard', effects: ['read'], permissions: ['read_local'], triggers: ['explicit test'], non_triggers: ['unrelated task'] }, null, 2)}\n`,
    'skill.yaml': `schema_version: px.skill-manifest/1.0\nid: ${skillId}\nversion: ${version}\nentrypoint: SKILL.md\ndomain: px-standard\n`,
    'contracts/input.schema.json': `${JSON.stringify({ type: 'object', additionalProperties: false, properties: {} }, null, 2)}\n`,
    'tests/contract.json': `${JSON.stringify({ schema_version: 'px.skill-test/1.1', cases: [{ name: 'required-files', assertion: { kind: 'required-files', paths: ['SKILL.md', 'capability.json', 'skill.yaml'] } }] }, null, 2)}\n`,
    'resources/README.md': '# Resources\n\nBounded local resources only.\n'
  };
  const payload = {
    skill_id: skillId, version, owner: 'human:test-owner', builder_domain: 'px-standard',
    triggers: ['explicit test'], non_triggers: ['unrelated task'], permissions: ['read_local'], effects: ['read'],
    resources: ['resources/README.md'], contracts: ['contracts/input.schema.json'], tests: ['tests/contract.json'],
    provenance: { source: 'studio-guided-editor' }, editor_files: editorFiles, lifecycle: 'draft'
  };
  const posts = [];
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:skill-product', kind: 'skill', payload }, {
    bridge,
    postMessage: async message => { posts.push(message); return true; },
    confirmCreate: async () => true,
    materializeSkillPackage,
    assertInitialCreateAbsent: (kind, identity) => bridge.studioIdentityAbsence(kind, identity),
    reclaimSkillPackage: reclaimMaterializedSkillPackage,
    isVersionConflict: error => Boolean(exactStudioVersionConflictError(error))
  });
  assert.equal(outcome.status, 'created');
  assert.equal(posts.at(-1)?.type, 'studioDraftResult');

  const catalog = await bridge.catalog({ kind: 'skills', query: skillId, status: '', offset: 0, limit: 20, sort: 'id' });
  const skill = catalog.items.find(item => item.kind === 'studio-skill-revision' && item.details?.skill_id === skillId);
  assert.equal(skill?.details?.lifecycle_authentication?.status, 'candidate');
  assert.equal(skill?.details?.package_scope, 'project-studio');
  assert.match(String(skill?.details?.source_content_sha256 || ''), /^[a-f0-9]{64}$/);
});
