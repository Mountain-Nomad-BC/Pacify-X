'use strict';

const path = require('node:path');
const { newId, nowIso, sha256 } = require('./ids');

function registerVsCodeReadOnlyTools(vscode, toolBroker, workspaceRootProvider) {
  const disposables = [];
  disposables.push(toolBroker.register({
    toolId: 'vscode.active-editor.selection', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async ({ request, task }) => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.uri.scheme !== 'file') return { summary: 'No active file editor.', output: { available: false }, evidence: [] };
      const root = workspaceRootProvider?.(); const file = editor.document.uri.fsPath; if (root && !within(file, root)) throw new Error('active-editor-outside-workspace');
      const selection = editor.document.getText(editor.selection).slice(0, 50000);
      const relative = root ? path.relative(root, file).replaceAll('\\','/') : path.basename(file);
      return { summary: `Active editor ${relative}; selection ${selection.length} bytes.`, output: { file: relative, selection, languageId: editor.document.languageId, selectionEmpty: editor.selection.isEmpty }, evidence: [] };
    }
  }));
  disposables.push(toolBroker.register({
    toolId: 'vscode.diagnostics.active-file', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async () => {
      const editor = vscode.window.activeTextEditor; if (!editor) return { summary: 'No active editor.', output: [], evidence: [] };
      const rows = vscode.languages.getDiagnostics(editor.document.uri).slice(0, 200).map(d => ({ message: d.message.slice(0,1000), severity: d.severity, source: d.source || null, code: typeof d.code === 'object' ? d.code.value : d.code ?? null, range: { start: { line:d.range.start.line, character:d.range.start.character }, end:{ line:d.range.end.line, character:d.range.end.character } } }));
      return { summary: `${rows.length} diagnostic(s) on active file.`, output: rows, evidence: [] };
    }
  }));
  disposables.push(toolBroker.register({
    toolId: 'vscode.workspace.find-files', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async ({ request }) => {
      const include = String(request.arguments.include || '**/*').slice(0,500); const exclude = request.arguments.exclude == null ? '**/{node_modules,.git,.quarantine}/**' : String(request.arguments.exclude).slice(0,500); const max = Math.max(1,Math.min(200,Number(request.arguments.maxResults||80)));
      const roots = vscode.workspace.workspaceFolders || []; const uris = await vscode.workspace.findFiles(include, exclude, max); const rows = uris.filter(u=>u.scheme==='file').map(uri => { const owner=roots.find(r=>within(uri.fsPath,r.uri.fsPath)); return owner ? path.relative(owner.uri.fsPath,uri.fsPath).replaceAll('\\','/') : path.basename(uri.fsPath); });
      return { summary: `${rows.length} workspace file match(es).`, output: rows, evidence: [] };
    }
  }));
  return { dispose(){ for(const d of disposables.splice(0))d?.dispose?.(); } };
}

function within(candidate, root) { const rel=path.relative(path.resolve(root),path.resolve(candidate)); return rel===''||(!rel.startsWith('..')&&!path.isAbsolute(rel)); }
module.exports = { registerVsCodeReadOnlyTools, within };
