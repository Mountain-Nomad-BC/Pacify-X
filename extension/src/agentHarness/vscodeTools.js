'use strict';

const path = require('node:path');
const fs = require('node:fs');

function registerVsCodeReadOnlyTools(vscode, toolBroker, workspaceRootProvider) {
  const disposables = [];
  disposables.push(toolBroker.register({
    toolId: 'vscode.active-editor.selection', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async ({ request, task }) => {
      const selected = readScopedEditor(vscode, workspaceRootProvider);
      if (!selected) return { summary: 'No active file editor.', output: { available: false }, evidence: [] };
      return { summary: `Active editor ${selected.relative}; selection ${selected.selection.length} characters.`, output: { file: selected.relative, selection: selected.selection, languageId: selected.languageId, selectionEmpty: selected.selectionEmpty }, evidence: [] };
    }
  }));
  disposables.push(toolBroker.register({
    toolId: 'vscode.diagnostics.active-file', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async () => {
      const root = selectedWorkspace(workspaceRootProvider);
      const editor = vscode.window.activeTextEditor; if (!editor) return { summary: 'No active editor.', output: [], evidence: [] };
      if (editor.document.uri.scheme !== 'file') throw new Error('workspace-file-scheme-invalid');
      const file = editor.document.uri.fsPath; const before = scopedFile(file, root);
      const rows = vscode.languages.getDiagnostics(editor.document.uri).slice(0, 200).map(d => ({ message: d.message.slice(0,1000), severity: d.severity, source: d.source || null, code: typeof d.code === 'object' ? d.code.value : d.code ?? null, range: { start: { line:d.range.start.line, character:d.range.start.character }, end:{ line:d.range.end.line, character:d.range.end.character } } }));
      assertWorkspace(workspaceRootProvider, root);
      if (scopedFile(file, root) !== before || editor.document.uri.fsPath !== file) throw new Error('workspace-file-changed');
      return { summary: `${rows.length} diagnostic(s) on active file.`, output: rows, evidence: [] };
    }
  }));
  disposables.push(toolBroker.register({
    toolId: 'vscode.workspace.find-files', effectClass: 'READ_ONLY', requireApproval: false,
    execute: async ({ request }) => {
      const root = selectedWorkspace(workspaceRootProvider);
      const include = boundedPattern(request.arguments.include ?? '**/*');
      const exclude = boundedPattern(request.arguments.exclude ?? '**/{node_modules,.git,.quarantine}/**');
      const max = Number(request.arguments.maxResults ?? 80);
      if (!Number.isSafeInteger(max) || max < 1 || max > 200) throw new Error('workspace-find-limit-invalid');
      const query = new vscode.RelativePattern(vscode.Uri.file(root.path), include);
      const uris = await vscode.workspace.findFiles(query, exclude, max);
      assertWorkspace(workspaceRootProvider, root);
      if (!Array.isArray(uris) || uris.length > max) throw new Error('workspace-find-result-limit');
      const rows = [];
      for (const uri of uris) {
        if (uri?.scheme !== 'file' || typeof uri.fsPath !== 'string' || !within(uri.fsPath, root.path)) continue;
        try { scopedFile(uri.fsPath, root); } catch { continue; }
        rows.push(path.relative(root.path, uri.fsPath).replaceAll('\\', '/'));
      }
      assertWorkspace(workspaceRootProvider, root);
      return { summary: `${rows.length} workspace file match(es).`, output: rows, evidence: [] };
    }
  }));
  return { dispose(){ for(const d of disposables.splice(0))d?.dispose?.(); } };
}

function within(candidate, root) { const rel=path.relative(path.resolve(root),path.resolve(candidate)); return rel===''||(rel !== '..' && !rel.startsWith('..' + path.sep)&&!path.isAbsolute(rel)); }
// Conservative synchronous path checks. These reject observed links and
// rebinding; they are not a native directory-handle pin against an OS adversary.
function physicalIdentity(candidate, directory) {
  const absolute = path.resolve(candidate); const anchor = path.parse(absolute).root;
  let cursor = anchor; let stat = fs.lstatSync(cursor);
  for (const part of absolute.slice(anchor.length).split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, part); stat = fs.lstatSync(cursor);
    if (stat.isSymbolicLink()) throw new Error('workspace-link-denied');
    if (cursor !== absolute && !stat.isDirectory()) throw new Error('workspace-ancestor-invalid');
  }
  if (directory ? !stat.isDirectory() : !stat.isFile() || stat.nlink !== 1) throw new Error('workspace-physical-kind-invalid');
  return JSON.stringify([stat.dev, stat.ino, path.normalize(fs.realpathSync.native(absolute))]);
}
function selectedWorkspace(provider) {
  const value = provider?.();
  if (typeof value !== 'string' || !value || !path.isAbsolute(value)) throw new Error('workspace-root-unavailable');
  const root = path.resolve(value);
  return { path: root, identity: physicalIdentity(root, true) };
}
function assertWorkspace(provider, root) {
  const current = selectedWorkspace(provider);
  if (current.path !== root.path || current.identity !== root.identity) throw new Error('workspace-scope-changed');
}
function scopedFile(file, root) {
  if (typeof file !== 'string' || !path.isAbsolute(file) || !within(file, root.path)) throw new Error('file-outside-workspace');
  return physicalIdentity(file, false);
}
function boundedPattern(value) {
  if (typeof value !== 'string' || !value || value.length > 500 || value.includes('\0') || path.isAbsolute(value) || value.replaceAll('\\', '/').split('/').includes('..')) throw new Error('workspace-find-argument-invalid');
  return value;
}
function readScopedEditor(vscode, provider) {
  const root = selectedWorkspace(provider); const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== 'file') return null;
  const file = editor.document.uri.fsPath; const before = scopedFile(file, root);
  const selection = editor.document.getText(editor.selection).slice(0, 50000);
  assertWorkspace(provider, root);
  if (scopedFile(file, root) !== before || editor.document.uri.fsPath !== file) throw new Error('workspace-file-changed');
  return { file, relative: path.relative(root.path, file).replaceAll('\\', '/'), selection, languageId: editor.document.languageId, selectionEmpty: editor.selection.isEmpty };
}
module.exports = { registerVsCodeReadOnlyTools, within, readScopedEditor };
