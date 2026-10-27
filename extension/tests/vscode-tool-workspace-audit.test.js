'use strict';
const test = require('node:test'); const assert = require('node:assert/strict');
const fs = require('node:fs'); const os = require('node:os'); const path = require('node:path');
const { registerVsCodeReadOnlyTools } = require('../src/agentHarness/vscodeTools');
function fixture() {
  // The governed owner and focused runner bind os.tmpdir() to their registered
  // retained workspace; do not remove failed fixture evidence here.
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'px-tool-scope-'));
  const root = path.join(base, 'selected'); const other = path.join(base, 'other');
  fs.mkdirSync(root); fs.mkdirSync(other);
  const file = path.join(root, 'owned.txt'); const external = path.join(other, 'private.txt');
  fs.writeFileSync(file, 'owned fixture'); fs.writeFileSync(external, 'external canary');
  let selectedRoot = root; let reads = 0; let diagnostics = 0; let findInput;
  const editor = { document: { uri: { scheme: 'file', fsPath: file }, languageId: 'plaintext', getText() { reads++; return 'owned fixture'; } }, selection: { isEmpty: false } };
  const vscode = { window: { activeTextEditor: editor }, languages: { getDiagnostics() { diagnostics++; return []; } },
    RelativePattern: class { constructor(base, pattern) { this.baseUri = base; this.pattern = pattern; } },
    Uri: { file: fsPath => ({ scheme: 'file', fsPath }) },
    workspace: { workspaceFolders: [{ uri: { fsPath: root } }, { uri: { fsPath: other } }], async findFiles(include) { findInput=include; return [{ scheme: 'file', fsPath: file }, { scheme: 'file', fsPath: external }]; } } };
  const tools = new Map(); registerVsCodeReadOnlyTools(vscode, { register(tool) { tools.set(tool.toolId, tool); return { dispose() {} }; } }, () => selectedRoot);
  return { base, root, other, file, external, editor, vscode, tools, select(value) { selectedRoot=value; }, reads:()=>reads, diagnostics:()=>diagnostics, findInput:()=>findInput,
    run(id, args={}) { return tools.get(id).execute({request:{arguments:args}}); } };
}
for (const id of ['vscode.active-editor.selection', 'vscode.diagnostics.active-file', 'vscode.workspace.find-files']) test(`${id} refuses absent selected workspace`, async () => {
  const f=fixture(); f.select(null); await assert.rejects(f.run(id), /workspace|scope/i); assert.equal(f.reads(),0); assert.equal(f.diagnostics(),0);
});
for (const id of ['vscode.active-editor.selection', 'vscode.diagnostics.active-file']) test(`${id} refuses another workspace before content access`, async () => {
  const f=fixture(); f.editor.document.uri.fsPath=f.external; await assert.rejects(f.run(id), /workspace|scope/i); assert.equal(f.reads(),0); assert.equal(f.diagnostics(),0);
});
test('selected physical editor remains readable', async () => { const f=fixture(); const r=await f.run('vscode.active-editor.selection'); assert.equal(r.output.selection,'owned fixture'); assert.equal(r.output.file,'owned.txt'); });
test('file discovery restricts query and output to selected workspace', async () => { const f=fixture(); const r=await f.run('vscode.workspace.find-files'); assert.deepEqual(r.output,['owned.txt']); assert.equal(f.findInput().pattern,'**/*'); });
test('actual junction cannot expose an external editor', async () => {
  const f=fixture(); const link=path.join(f.root,'escape'); fs.symlinkSync(f.other,link,process.platform==='win32'?'junction':'dir'); f.editor.document.uri.fsPath=path.join(link,'private.txt');
  await assert.rejects(f.run('vscode.active-editor.selection'), /workspace|scope|link/i); assert.equal(f.reads(),0); assert.equal(fs.readFileSync(f.external,'utf8'),'external canary');
});
test('workspace switch during asynchronous discovery invalidates result', async () => { const f=fixture(); f.vscode.workspace.findFiles=async()=>{f.select(f.other);return [{scheme:'file',fsPath:f.file}];}; await assert.rejects(f.run('vscode.workspace.find-files'), /workspace|scope/i); });
test('non-finite discovery limit is rejected before query', async () => { const f=fixture(); await assert.rejects(f.run('vscode.workspace.find-files',{maxResults:'NaN'}), /limit|argument/i); assert.equal(f.findInput(),undefined); });

test('actual hardlink cannot expose another workspace file', async () => { const f=fixture(); const link=path.join(f.root,'alias.txt'); fs.linkSync(f.external,link);f.editor.document.uri.fsPath=link;await assert.rejects(f.run('vscode.active-editor.selection'), /workspace|scope|kind/i);assert.equal(f.reads(),0); });
test('selected workspace junction is refused before diagnostics', async () => { const f=fixture(); const link=path.join(f.base,'root-alias');fs.symlinkSync(f.root,link,process.platform==='win32'?'junction':'dir');f.select(link);await assert.rejects(f.run('vscode.diagnostics.active-file'), /workspace|link/i);assert.equal(f.diagnostics(),0); });
test('file identity replacement during editor access invalidates result', async () => {const f=fixture();f.editor.document.getText=()=>{const replacement=path.join(f.root,'replacement.txt');fs.writeFileSync(replacement,'replacement');fs.renameSync(replacement,f.file);return 'original';};await assert.rejects(f.run('vscode.active-editor.selection'), /workspace|changed/i);});
test('ordinary filename beginning with two dots is inside workspace', async () => {const f=fixture();const file=path.join(f.root,'..notes.txt');fs.writeFileSync(file,'owned fixture');f.editor.document.uri.fsPath=file;assert.equal((await f.run('vscode.active-editor.selection')).output.file,'..notes.txt');});

for (const selected of ['other', 'absent', 'current']) test(`actual registered console editor context uses ${selected} selected root`, () => {
  const { registerAgentConsole } = require('../src/agentHarness/registerAgentConsole');
  const f=fixture(); let view;
  f.vscode.window.registerWebviewViewProvider=(_id, provider)=>{view=provider;return {dispose(){}};};
  f.vscode.commands={registerCommand:()=>({dispose(){}})};
  const root=selected==='other'?f.other:selected==='current'?f.root:null;
  const registration=registerAgentConsole(f.vscode,{workspaceState:{get(){},async update(){}}},{workspaceRootProvider:()=>root});
  try {const refs=view._editorRefs();assert.equal(refs.length,selected==='current'?1:0);assert.equal(f.reads(),selected==='current'?1:0);}
  finally {registration.dispose();}
});
