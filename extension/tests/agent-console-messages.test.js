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
