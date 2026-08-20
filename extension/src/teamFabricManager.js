'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { Worker } = require('node:worker_threads');

const ENTITY_FILES = new Map([
  ['COMPANY.MD', 'company'], ['TEAM.MD', 'team'], ['AGENT.MD', 'agent'], ['PROJECT.MD', 'project'],
  ['TASK.MD', 'task'], ['SKILL.MD', 'skill']
]);
const MAX_FILES = 10000;
const MAX_FILE_BYTES = 8 * 1024 * 1024;

function digestFile(file) {
  const digest = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try { let read; while ((read = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) digest.update(buffer.subarray(0, read)); }
  finally { fs.closeSync(fd); }
  return digest.digest('hex');
}
function safeSlug(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 160) || 'unnamed';
}
function boundedRoot(value) {
  const root = path.resolve(String(value || ''));
  if (!value || root === path.parse(root).root) throw new Error('team-pack-root-must-be-bounded');
  const stat = fs.lstatSync(root);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('team-pack-root-must-be-plain-directory');
  return root;
}
function relative(root, target) { return path.relative(root, target).split(path.sep).join('/'); }
function readFrontmatterIdentity(file) {
  const stat = fs.statSync(file); if (stat.size > 256 * 1024) return null;
  const text = fs.readFileSync(file, 'utf8').slice(0, 256 * 1024);
  const block = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---/);
  if (!block) return null;
  const match = block[1].match(/^(?:name|slug|id):\s*["']?([^\r\n"']+)/mi);
  return match ? match[1].trim() : null;
}

function inventoryTeamPack(sourceRoot, existingIds = []) {
  const root = boundedRoot(sourceRoot); const existing = new Set(existingIds.map(safeSlug));
  const stack = [root]; const files = []; const entities = []; const warnings = []; const licenses = [];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const target = path.join(current, entry.name); const stat = fs.lstatSync(target);
      if (stat.isSymbolicLink()) { warnings.push({ code: 'link-excluded', path: relative(root, target) }); continue; }
      if (entry.isDirectory()) { stack.push(target); continue; }
      if (!entry.isFile()) { warnings.push({ code: 'unsupported-entry', path: relative(root, target) }); continue; }
      if (files.length >= MAX_FILES) throw new Error('team-pack-file-limit-exceeded');
      if (stat.size > MAX_FILE_BYTES) { warnings.push({ code: 'oversized-file-excluded', path: relative(root, target), bytes: stat.size }); continue; }
      const record = { path: relative(root, target), bytes: stat.size, sha256: digestFile(target) }; files.push(record);
      if (/^(LICENSE|COPYING)(\.|$)/i.test(entry.name)) licenses.push(record);
      const kind = ENTITY_FILES.get(entry.name.toUpperCase());
      if (kind) {
        const identity = readFrontmatterIdentity(target) || path.basename(path.dirname(target)) || path.parse(entry.name).name;
        const slug = safeSlug(identity); const collision = existing.has(slug);
        entities.push({ kind, slug, path: record.path, sha256: record.sha256, bytes: record.bytes, collision, disposition: collision ? 'skip' : 'stage-candidate' });
      }
    }
  }
  files.sort((a, b) => a.path.localeCompare(b.path)); entities.sort((a, b) => a.kind.localeCompare(b.kind) || a.slug.localeCompare(b.slug));
  const manifestSha256 = crypto.createHash('sha256').update(JSON.stringify(files)).digest('hex');
  if (!licenses.length) warnings.push({ code: 'license-not-found', path: '.' });
  return {
    schema_version: 'agentcompanies/v1-preview', operation: 'team-pack-dry-run', dry_run: true,
    source: { label: path.basename(root), root_sha256: crypto.createHash('sha256').update(root).digest('hex') },
    totals: { files: files.length, bytes: files.reduce((sum, item) => sum + item.bytes, 0), entities: entities.length, collisions: entities.filter(item => item.collision).length, warnings: warnings.length },
    manifest_sha256: manifestSha256, licenses, entities, warnings,
    guarantees: { canonical_registry_mutated: false, source_mutated: false, credentials_copied: false, machine_paths_exported: false }
  };
}

function inventoryTeamPackAsync(sourceRoot, existingIds = [], options = {}) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(path.join(__dirname, 'teamFabricWorker.js'), { workerData: { sourceRoot, existingIds } });
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return; settled = true; clearTimeout(timer);
      options.signal?.removeEventListener?.('abort', onAbort); callback(value);
    };
    const onAbort = () => {
      void worker.terminate();
      finish(reject, Object.assign(new Error('Team package inventory cancelled.'), { name: 'AbortError' }));
    };
    const timer = setTimeout(() => {
      void worker.terminate();
      finish(reject, new Error('Team package inventory exceeded its 60 second deadline.'));
    }, Math.max(1000, Number(options.timeoutMs) || 60_000));
    worker.once('message', message => {
      void worker.terminate();
      if (message?.ok === true) finish(resolve, message.result);
      else finish(reject, new Error(`Team package inventory failed: ${String(message?.error || 'invalid worker response').slice(0, 500)}`));
    });
    worker.once('error', error => finish(reject, error));
    worker.once('exit', code => { if (!settled && code !== 0) finish(reject, new Error(`Team package inventory worker exited with code ${code}.`)); });
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener?.('abort', onAbort, { once: true });
  });
}

function stageTeamPack(workspaceRoot, preview, options = {}) {
  const workspace = boundedRoot(workspaceRoot);
  if (!preview?.dry_run || preview.operation !== 'team-pack-dry-run' || !/^[a-f0-9]{64}$/.test(String(preview.manifest_sha256 || ''))) throw new Error('verified-team-pack-preview-required');
  const collisionMode = String(options.collisionMode || options.collision_mode || 'skip');
  if (!['skip', 'rename', 'replace-candidate-only'].includes(collisionMode)) throw new Error('unsupported-team-pack-collision-mode');
  const selected = new Set((options.selection || preview.entities.map(item => `${item.kind}:${item.slug}`)).map(String));
  const staged = [];
  for (const entity of preview.entities) {
    if (!selected.has(`${entity.kind}:${entity.slug}`)) continue;
    if (entity.collision && collisionMode === 'skip') continue;
    staged.push({ ...entity, canonical: false, admission_state: 'candidate', staged_slug: entity.collision && collisionMode === 'rename' ? `${entity.slug}-candidate-${entity.sha256.slice(0, 8)}` : entity.slug });
  }
  const receipt = {
    schema_version: '1.0', import_id: `team-pack-${crypto.randomUUID()}`, operation: 'team-pack-stage-candidates', created_utc: new Date().toISOString(),
    source: preview.source, source_manifest_sha256: preview.manifest_sha256, collision_mode: collisionMode,
    selected_count: selected.size, staged_count: staged.length, staged, canonical_registry_mutated: false,
    next_gate: 'Pacify-X provenance, license, collision, contract, effect, and skill admission review'
  };
  const directory = path.join(workspace, '.engineering-bootstrap', 'coordination', 'imports');
  fs.mkdirSync(directory, { recursive: true });
  const output = path.join(directory, `${receipt.import_id}.json`); const temporary = `${output}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' }); fs.renameSync(temporary, output);
  return { receipt, path: output };
}

function workerAdapters(context = {}) {
  const workspace = context.workspaceRoot ? path.resolve(context.workspaceRoot) : null;
  const extensionRoot = context.extensionRoot ? path.resolve(context.extensionRoot) : null;
  return [
    { id: 'human-local', version: '1.0', kind: 'human', status: workspace ? 'ready' : 'blocked', capabilities: ['review', 'approval', 'manual-execution'], doctor: workspace ? [] : ['workspace-unresolved'], native_session: false },
    { id: 'vscode-compatible-host', version: '1.0', kind: 'hybrid', status: context.appName ? 'ready' : 'unavailable', capabilities: ['webview', 'workspace-context', 'commands', 'stdio-mcp'], doctor: context.appName ? [] : ['host-identity-unavailable'], native_session: false },
    { id: 'codex-cli', version: '1.0', kind: 'agent', status: context.codexAuthenticated ? 'ready' : 'authentication-required', capabilities: ['execute', 'cancel', 'json-events', 'portable-resume'], doctor: context.codexAuthenticated ? [] : ['verified-chatgpt-login-required'], native_session: false, billable_api_fallback: false },
    { id: 'ollama-loopback', version: '1.0', kind: 'local_model', status: context.ollamaEnabled ? 'configured-not-probed' : 'disabled', capabilities: ['local-chat'], doctor: context.ollamaEnabled ? ['probe-on-explicit-use'] : [], native_session: false, billable_api_fallback: false },
    { id: 'pacify-x-stdio-mcp', version: '1.0', kind: 'system', status: extensionRoot && fs.existsSync(path.join(extensionRoot, 'server', 'index.js')) ? 'ready' : 'build-required', capabilities: ['context', 'catalog', 'coordination', 'memory', 'team-pack-preview'], doctor: [], native_session: false }
  ].map(adapter => ({ ...adapter, workspace_resolved: Boolean(workspace), executor_identity: adapter.id, authentication_identity: adapter.id === 'codex-cli' ? (context.codexAuthenticated ? 'ChatGPT verified' : 'unavailable') : 'not-applicable', billing_identity: 'not-inferred' }));
}

module.exports = { ENTITY_FILES, inventoryTeamPack, inventoryTeamPackAsync, stageTeamPack, workerAdapters };
