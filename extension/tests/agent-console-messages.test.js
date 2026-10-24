'use strict';
const test=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'); const os=require('node:os'); const path=require('node:path');
const {MESSAGE_VERSION,ASSET_PROTOCOL,validateInbound}=require('../src/agentHarness/agentConsoleMessages');
const {AgentConsoleViewProvider,withinProject}=require('../src/agentHarness/agentConsoleView');
test('agent console protocol rejects unknown fields and unsafe IDs',()=>{assert.equal(validateInbound({schemaVersion:MESSAGE_VERSION,type:'ready',assetProtocol:ASSET_PROTOCOL}).type,'ready');assert.throws(()=>validateInbound({schemaVersion:MESSAGE_VERSION,type:'cancelRun',runId:'../x'}),/invalid/);assert.throws(()=>validateInbound({schemaVersion:MESSAGE_VERSION,type:'refresh',extra:true}),/invalid/);});

test('agent console never collects selected text outside its active project', t => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'px-agent-project-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const project=path.join(root,'project'); fs.mkdirSync(project);
  const inside=path.join(project,'inside.txt'); const outside=path.join(root,'outside.txt');
  fs.writeFileSync(inside,'inside'); fs.writeFileSync(outside,'outside');
  assert.equal(withinProject(inside,project),true);
  assert.equal(withinProject(outside,project),false);
  let readCount=0;
  const editor={document:{uri:{scheme:'file',fsPath:outside},getText:()=>{readCount+=1;return 'secret';}},selection:{}};
  const owner={vscode:{window:{activeTextEditor:editor},workspace:{workspaceFolders:[{uri:{fsPath:project}}]}}};
  assert.deepEqual(AgentConsoleViewProvider.prototype._editorRefs.call(owner),[]);
  assert.equal(readCount,0);
  editor.document.uri.fsPath=inside;
  assert.equal(AgentConsoleViewProvider.prototype._editorRefs.call(owner)[0].content,'secret');
  assert.equal(readCount,1);
  owner.vscode.workspace.workspaceFolders=[];
  assert.deepEqual(AgentConsoleViewProvider.prototype._editorRefs.call(owner),[]);
});

test('agent console executePreparedGroup admits only the canonical reference', () => {
  const reference = { schema_version: 'px.prepared-group-reference/1.0', plan_id: 'task-plan-0123456789abcdef01234567', plan_sha256: 'a'.repeat(64) };
  assert.equal(validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference }).type, 'executePreparedGroup');
  // Browser-created model branches, placements, approvals or plan bodies are
  // never part of the transport: the reference is the only admitted field set.
  assert.throws(() => validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference, placements: { x: {} } }), /invalid/);
  assert.throws(() => validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference: { ...reference, plan_id: 'task-plan-ZZZZ' } }), /invalid/);
  assert.throws(() => validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference: { ...reference, plan_sha256: 'short' } }), /invalid/);
  assert.throws(() => validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup' }), /invalid/);
});

test('agent console reports unavailable prepared-group execution without downgrade', async () => {
  const provider = Object.create(AgentConsoleViewProvider.prototype);
  provider.harness = { eventBus: { emit: (type, event) => { provider.emitted = [type, event]; } } };
  let error = null;
  provider._error = async (code, detail) => { error = { code, detail }; };
  provider.publish = async () => {};
  await provider._handle({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference: { schema_version: 'px.prepared-group-reference/1.0', plan_id: 'task-plan-0123456789abcdef01234567', plan_sha256: 'a'.repeat(64) } });
  assert.equal(error.code, 'prepared-group-execution-unavailable');
  assert.equal(provider.emitted, undefined);
});

test('agent console prepared-group execution failure is surfaced, never masked', async () => {
  const provider = Object.create(AgentConsoleViewProvider.prototype);
  provider.onDiagnostic = () => {};
  provider.harness = { eventBus: { emit: () => { throw new Error('emit-only-on-success'); } } };
  provider.executePreparedGroup = async () => { throw new Error('host boundary rejected the run'); };
  let error = null;
  provider._error = async (code, detail) => { error = { code, detail }; };
  provider.publish = async () => {};
  await provider._handle({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference: { schema_version: 'px.prepared-group-reference/1.0', plan_id: 'task-plan-0123456789abcdef01234567', plan_sha256: 'a'.repeat(64) } });
  assert.equal(error.code, 'prepared-group-execution-rejected');
  assert.match(error.detail, /host boundary rejected/);
});
