'use strict';

const cp = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { Worker } = require('worker_threads');
const { processTreeSpawnOptions, terminateProcessTree } = require('./processTree');

const SCHEMA = 'px.environment-capability-map/2.0';
const LEGACY_SCHEMA = 'px.environment-capability-map/1.0';
const MAX_OUTPUT = 8 * 1024 * 1024;
const MAX_SCAN_ENTRIES = 20000;
const MAX_SCAN_DEPTH = 7;
const MAX_ENV_FILE_BYTES = 1024 * 1024;
// Extension changes invalidate this inventory immediately. Keep unchanged host
// evidence current for the same bounded daily window used by the environment
// doctor so a normal dashboard session does not become empty after five minutes.
const DEFAULT_DISCOVERY_TTL_MS = 24 * 60 * 60 * 1000;
const TOOL_PROBES = [
  ['python', ['--version']], ['node', ['--version']], ['npm', ['--version']], ['git', ['--version']],
  ['docker', ['--version']], ['ollama', ['--version']], ['uv', ['--version']], ['code', ['--version']],
  ['conda', ['--version']], ['pipx', ['--version']], ['pnpm', ['--version']], ['yarn', ['--version']]
];

function sha(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function cleanText(value, maximum = 500) { return String(value || '').replace(/[\r\n\0]+/g, ' ').trim().slice(0, maximum); }
function nonBillableEnv() {
  const denied = /^(OPENAI|AZURE_OPENAI|ANTHROPIC|GOOGLE|GEMINI|CODEX|MISTRAL|COHERE|GROQ|TOGETHER|OPENROUTER|PERPLEXITY|XAI|DEEPSEEK)_API_KEY$/i;
  return Object.fromEntries(Object.entries(process.env).filter(([key]) => !denied.test(key)));
}
function runBounded(command, args, options = {}) {
  return new Promise(resolve => {
    let stdout = ''; let stderr = ''; let settled = false;
    let child;
    try {
      child = cp.spawn(command, args, {
        cwd: options.cwd, windowsHide: true, shell: false,
        ...processTreeSpawnOptions(),
        env: { ...nonBillableEnv(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', NO_COLOR: '1' }
      });
    } catch (error) { resolve({ status: null, stdout, stderr: error.message }); return; }
    const onAbort = () => { terminateProcessTree(child); finish({ status: null, stdout, stderr: `${stderr}probe-cancelled`, cancelled: true }); };
    const finish = result => { if (!settled) { settled = true; clearTimeout(timer); options.signal?.removeEventListener?.('abort', onAbort); resolve(result); } };
    const capture = (target, chunk) => {
      const next = target + chunk.toString('utf8');
      if (next.length > MAX_OUTPUT) { terminateProcessTree(child); return next.slice(0, MAX_OUTPUT); }
      return next;
    };
    child.stdout?.on('data', chunk => { stdout = capture(stdout, chunk); });
    child.stderr?.on('data', chunk => { stderr = capture(stderr, chunk); });
    child.on('error', error => finish({ status: null, stdout, stderr: `${stderr}${error.message}` }));
    child.on('close', code => finish({ status: code, stdout, stderr }));
    const timer = setTimeout(() => { terminateProcessTree(child); finish({ status: null, stdout, stderr: `${stderr}probe-timeout` }); }, options.timeout || 10000);
    if (options.signal?.aborted) { onAbort(); return; }
    options.signal?.addEventListener?.('abort', onAbort, { once: true });
  });
}
function parseJson(result, fallback) {
  if (!result || result.status !== 0) return fallback;
  try { return JSON.parse(result.stdout); } catch { return fallback; }
}
function normalizeExtensions(extensions = []) {
  const records = extensions.map(extension => {
    const manifest = extension.packageJSON || {};
    const contributes = manifest.contributes && typeof manifest.contributes === 'object' ? manifest.contributes : {};
    const commands = (Array.isArray(contributes.commands) ? contributes.commands : []).map(item => ({
      id: cleanText(item?.command, 240), invocation: `vscode.commands.executeCommand('${cleanText(item?.command, 240)}', ...args)`,
      title: cleanText(item?.title, 240), expected_inputs: 'Arguments are not declared by the extension manifest; inspect provider documentation before invocation.',
      expected_outputs: 'Return contract is not declared by the extension manifest.', enablement: cleanText(item?.enablement, 500) || null
    })).filter(item => item.id).sort((a, b) => a.id.localeCompare(b.id));
    const capabilityFlags = manifest.capabilities && typeof manifest.capabilities === 'object' ? manifest.capabilities : {};
    return {
      id: cleanText(extension.id || manifest.name, 200), name: cleanText(manifest.displayName || manifest.name || extension.id, 240),
      version: cleanText(manifest.version, 80), publisher: cleanText(manifest.publisher, 160), active: Boolean(extension.isActive),
      builtin: Boolean(manifest.isBuiltin), extension_kind: Array.isArray(manifest.extensionKind) ? manifest.extensionKind.map(String) : [],
      contribution_points: Object.keys(contributes).sort(),
      capabilities: Object.keys(contributes).sort().map(point => ({ id: `contribution:${point}`, kind: point, provider: cleanText(extension.id || manifest.name, 200), invocation: point === 'commands' ? 'See commands[]' : 'VS Code contribution-point contract', expected_inputs: 'Defined by the VS Code contribution point and provider manifest.', expected_outputs: 'Defined by the VS Code host contract; provider-specific output is not inferred.' })),
      commands,
      api_contract: { exported_api_detected: false, activation_attempted: false, invocation: 'vscode.extensions.getExtension(id)?.exports only after separately approved activation', expected_inputs: 'Provider-defined; not inferred', expected_outputs: 'Provider-defined; not inferred' },
      dependencies: (Array.isArray(manifest.extensionDependencies) ? manifest.extensionDependencies : []).map(item => cleanText(item, 200)).filter(Boolean).sort(),
      activation_events: (Array.isArray(manifest.activationEvents) ? manifest.activationEvents : []).map(item => cleanText(item, 300)).filter(Boolean).sort(),
      permissions_resources: {
        extension_kind: Array.isArray(manifest.extensionKind) ? manifest.extensionKind.map(String) : [],
        workspace_trust: capabilityFlags.untrustedWorkspaces || { supported: 'not-declared' },
        virtual_workspaces: capabilityFlags.virtualWorkspaces || { supported: 'not-declared' },
        resource_roots: ['VS Code extension host', 'declared contribution points'], credential_access_inferred: false
      },
      constraints: ['Metadata detection does not activate the extension.', 'Command arguments and return types are unknown unless the provider declares them.'],
      known_conflicts: [],
      integration_status: 'detected-metadata-only'
    };
  }).filter(item => item.id).sort((a, b) => a.id.localeCompare(b.id));
  const owners = new Map();
  for (const record of records) for (const command of record.commands) {
    if (!owners.has(command.id)) owners.set(command.id, []); owners.get(command.id).push(record.id);
  }
  for (const record of records) for (const command of record.commands) {
    const commandOwners = owners.get(command.id) || [];
    if (commandOwners.length > 1) record.known_conflicts.push({ kind: 'duplicate-command-provider', resource: command.id, providers: commandOwners });
  }
  return records;
}
async function toolInventory(run = runBounded, pythonPath = 'python') {
  const records = new Array(TOOL_PROBES.length);
  let cursor = 0;
  const worker = async () => {
    while (cursor < TOOL_PROBES.length) {
      const index = cursor; cursor += 1;
      const [tool, args] = TOOL_PROBES[index];
    const command = tool === 'python' ? pythonPath : tool;
    const [result, location] = await Promise.all([
      run(command, args, { timeout: 5000 }),
      run(process.platform === 'win32' ? 'where.exe' : 'which', [command], { timeout: 5000 })
    ]);
    const explicitExecutable = path.isAbsolute(command) && (() => { try { return fs.statSync(command).isFile(); } catch { return false; } })() ? path.resolve(command) : null;
    const executable = explicitExecutable || (location.status === 0 ? cleanText(location.stdout.split(/\r?\n/).find(Boolean), 1000) : null);
    const available = result.status === 0;
      records[index] = {
      id: tool, command: cleanText(command, 500), executable, available,
      version: cleanText(result.stdout || result.stderr, 300), probe: args.join(' '),
      install_source: inferInstallSource(executable), capabilities: toolCapabilities(tool),
      project_requirements: [], dependencies: tool === 'npm' ? ['node'] : tool === 'pipx' ? ['python'] : [],
      environment_requirements: tool === 'docker' ? ['Docker service/daemon'] : tool === 'ollama' ? ['Loopback Ollama service'] : [],
      health: available ? 'healthy-version-probe' : 'unavailable', last_verified_utc: new Date().toISOString(),
      update: { available: 'unknown', reason: 'Network update checks are outside read-only discovery.' },
      conflicts: [], trust: { state: 'detected-not-admitted', invocation_authorized: false }
      };
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, TOOL_PROBES.length) }, worker));
  return records;
}

function inferInstallSource(executable) {
  const value = String(executable || '').replaceAll('\\', '/').toLowerCase();
  if (!value) return 'unresolved-path';
  if (value.includes('/scoop/')) return 'scoop';
  if (value.includes('/chocolatey/')) return 'chocolatey';
  if (value.includes('/node_modules/')) return 'node-package';
  if (value.includes('/conda') || value.includes('/miniconda') || value.includes('/anaconda')) return 'conda';
  if (value.includes('/program files/')) return 'system-installer';
  if (value.includes('/windows/system32/')) return 'operating-system';
  if (value.includes('/.local/') || value.includes('/appdata/local/')) return 'user-local';
  return 'path-discovered';
}

function toolCapabilities(tool) {
  return ({
    python: ['python-runtime', 'package-management'], node: ['javascript-runtime'], npm: ['javascript-package-management'],
    git: ['source-control'], docker: ['container-runtime'], ollama: ['local-model-runtime'], uv: ['python-environment-management'],
    code: ['vscode-cli'], conda: ['python-environment-management', 'package-management'], pipx: ['isolated-python-application-management'],
    pnpm: ['javascript-package-management'], yarn: ['javascript-package-management']
  })[tool] || ['command-line-tool'];
}
async function packageInventory(run = runBounded, pythonPath = 'python', projectRoot = '') {
  const [pythonResult, npmGlobalResult] = await Promise.all([
    run(pythonPath, ['-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'], { timeout: 20000, cwd: projectRoot || undefined }),
    run('npm', ['ls', '-g', '--depth=0', '--json'], { timeout: 20000, cwd: projectRoot || undefined })
  ]);
  const python = parseJson(pythonResult, []).map(item => ({ name: cleanText(item.name, 240), version: cleanText(item.version, 120), manager: 'python-pip', scope: 'interpreter' })).filter(item => item.name).sort((a, b) => a.name.localeCompare(b.name));
  const npmGlobalJson = parseJson(npmGlobalResult, {});
  const npmGlobal = Object.entries(npmGlobalJson.dependencies || {}).map(([name, item]) => ({ name: cleanText(name, 240), version: cleanText(item?.version, 120), manager: 'npm', scope: 'global' })).sort((a, b) => a.name.localeCompare(b.name));
  let npmProject = [];
  if (projectRoot && fs.existsSync(path.join(projectRoot, 'package.json'))) {
    const projectResult = await run('npm', ['ls', '--depth=0', '--json'], { timeout: 20000, cwd: projectRoot });
    const projectJson = parseJson(projectResult, {});
    npmProject = Object.entries(projectJson.dependencies || {}).map(([name, item]) => ({ name: cleanText(name, 240), version: cleanText(item?.version, 120), manager: 'npm', scope: 'project' })).sort((a, b) => a.name.localeCompare(b.name));
  }
  return { python, npm_global: npmGlobal, npm_project: npmProject, probes: { python: pythonResult.status === 0, npm_global: npmGlobalResult.status === 0 } };
}

function admittedRoots(roots = []) {
  const result = [];
  for (const candidate of roots.filter(Boolean)) {
    const resolved = path.resolve(candidate);
    if (resolved === path.parse(resolved).root || result.includes(resolved)) continue;
    try { if (fs.statSync(resolved).isDirectory()) result.push(resolved); } catch { /* unavailable root */ }
  }
  return result;
}

function rootIdentity(value, platform = process.platform) {
  const pathFlavor = platform === 'win32' ? path.win32 : path.posix;
  const normalized = pathFlavor.normalize(String(value || '')).replace(/[\\/]+$/, '');
  return platform === 'win32' ? normalized.replaceAll('/', '\\').toLowerCase() : normalized;
}

function inspectRoots(roots = []) {
  const records = []; const admitted = []; const failures = []; const ambiguities = []; const physical = new Map();
  for (const candidate of roots.filter(Boolean)) {
    const requested = path.resolve(candidate); let resolved = requested; let state = 'available';
    if (requested === path.parse(requested).root) { failures.push({ code: 'filesystem-root-not-admitted', requested_root: requested }); records.push({ requested_root: requested, resolved_root: null, state: 'rejected' }); continue; }
    try {
      if (!fs.statSync(requested).isDirectory()) throw new Error('not-directory');
      resolved = fs.realpathSync.native?.(requested) || fs.realpathSync(requested);
    } catch (error) {
      state = error.message === 'not-directory' ? 'not-directory' : 'missing-or-unreadable';
      failures.push({ code: state, requested_root: requested }); records.push({ requested_root: requested, resolved_root: null, state }); continue;
    }
    const identity = rootIdentity(resolved);
    if (physical.has(identity)) {
      ambiguities.push({ code: 'duplicate-physical-root', requested_root: requested, canonical_root: physical.get(identity) });
      records.push({ requested_root: requested, resolved_root: resolved, state: 'alias' }); continue;
    }
    const overlap = admitted.find(root => isWithin(resolved, root) || isWithin(root, resolved));
    if (overlap) ambiguities.push({ code: 'nested-root-overlap', requested_root: requested, resolved_root: resolved, overlaps_root: overlap });
    physical.set(identity, resolved); admitted.push(resolved); records.push({ requested_root: requested, resolved_root: resolved, state });
  }
  return { admitted, records, failures, ambiguities };
}

function boundedTree(roots = []) {
  const rootInspection = inspectRoots(roots); const entries = []; const failures = [...rootInspection.failures]; const ambiguities = [...rootInspection.ambiguities]; let capped = false; let symbolicLinksSkipped = 0;
  const inspectPythonEnvironment = (root, directory, relative, depth) => {
    const marker = path.join(directory, 'pyvenv.cfg');
    try {
      const stat = fs.lstatSync(marker);
      if (stat.isFile() && entries.length < MAX_SCAN_ENTRIES) entries.push({ root, absolute: marker, relative: `${relative}/pyvenv.cfg`, name: 'pyvenv.cfg', depth: depth + 2, directory: false, file: true });
    } catch { return; }
    const siteRoots = [path.join(directory, 'Lib', 'site-packages')];
    try {
      for (const version of fs.readdirSync(path.join(directory, 'lib'), { withFileTypes: true })) {
        if (version.isDirectory() && /^python\d+(?:\.\d+)?$/i.test(version.name)) siteRoots.push(path.join(directory, 'lib', version.name, 'site-packages'));
      }
    } catch { /* no POSIX library layout */ }
    for (const siteRoot of siteRoots) {
      let packages; try { packages = fs.readdirSync(siteRoot, { withFileTypes: true }); } catch { continue; }
      for (const item of packages) {
        if (entries.length >= MAX_SCAN_ENTRIES) { capped = true; return; }
        if (item.isDirectory() && /\.dist-info$/i.test(item.name)) {
          const absolute = path.join(siteRoot, item.name);
          entries.push({ root, absolute, relative: path.relative(root, absolute).split(path.sep).join('/'), name: item.name, depth: depth + 5, directory: true, file: false });
        }
      }
    }
  };
  for (const root of rootInspection.admitted) {
    const pending = [{ target: root, depth: 0 }]; let cursor = 0;
    while (cursor < pending.length && entries.length < MAX_SCAN_ENTRIES) {
      const { target, depth } = pending[cursor]; cursor += 1;
      let children;
      try { children = fs.readdirSync(target, { withFileTypes: true }); } catch { failures.push({ code: 'directory-unreadable', root, relative: path.relative(root, target).split(path.sep).join('/') || '.' }); continue; }
      for (const child of children) {
        if (entries.length >= MAX_SCAN_ENTRIES) { capped = true; break; }
        if (child.isSymbolicLink()) { symbolicLinksSkipped += 1; continue; }
        const absolute = path.join(target, child.name);
        const relative = path.relative(root, absolute).split(path.sep).join('/');
        const record = { root, absolute, relative, name: child.name, depth: depth + 1, directory: child.isDirectory(), file: child.isFile() };
        entries.push(record);
        if (child.isDirectory() && /^\.venv.*$/i.test(child.name)) inspectPythonEnvironment(root, absolute, relative, depth);
        if (child.isDirectory() && depth < MAX_SCAN_DEPTH && !/^(\.git|node_modules|__pycache__|\.engineering-bootstrap|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.cache|\.px|Python|\.venv.*|dist|build|coverage)$/i.test(child.name)) pending.push({ target: absolute, depth: depth + 1 });
      }
    }
    if (entries.length >= MAX_SCAN_ENTRIES) capped = true;
  }
  return {
    roots: rootInspection.admitted, root_records: rootInspection.records, entries, capped, limit: MAX_SCAN_ENTRIES, max_depth: MAX_SCAN_DEPTH,
    failures, ambiguities, symbolic_links_skipped: symbolicLinksSkipped,
    completeness: capped || failures.length ? 'partial' : 'complete'
  };
}

function scanEnvironmentAsync(roots, options = {}) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(path.join(__dirname, 'discoveryWorker.js'), {
      workerData: {
        roots,
        pythonPath: options.pythonPath || 'python',
        currentPythonVersion: options.currentPythonVersion || null,
        generatedUtc: options.generatedUtc || new Date().toISOString()
      }
    });
    let settled = false;
    const onAbort = () => {
      void worker.terminate();
      const error = new Error('Environment discovery cancelled.'); error.name = 'AbortError';
      finish(reject, error);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      options.signal?.removeEventListener?.('abort', onAbort);
      callback(value);
    };
    const timer = setTimeout(() => {
      void worker.terminate();
      finish(reject, new Error('Environment discovery worker exceeded its 45 second deadline.'));
    }, 45_000);
    worker.once('message', message => {
      void worker.terminate();
      if (!message || message.ok !== true) {
        finish(reject, new Error(`Environment discovery worker failed: ${cleanText(message?.error || 'invalid worker response', 500)}`));
        return;
      }
      finish(resolve, message.result);
    });
    worker.once('error', error => finish(reject, error));
    worker.once('exit', code => {
      if (!settled && code !== 0) finish(reject, new Error(`Environment discovery worker exited with code ${code}.`));
    });
    if (options.signal?.aborted) { onAbort(); return; }
    options.signal?.addEventListener?.('abort', onAbort, { once: true });
  });
}

function isWithin(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function virtualEnvironmentInventory(tree, options = {}) {
  const activeCandidates = [options.pythonPath, process.env.VIRTUAL_ENV, process.env.CONDA_PREFIX].filter(Boolean).map(value => path.resolve(value));
  const byDirectory = new Map();
  for (const entry of tree.entries) {
    if (!entry.file || !['pyvenv.cfg', 'history'].includes(entry.name)) continue;
    if (entry.name === 'history' && path.basename(path.dirname(entry.absolute)).toLowerCase() !== 'conda-meta') continue;
    const directory = entry.name === 'history' ? path.dirname(path.dirname(entry.absolute)) : path.dirname(entry.absolute);
    if (!isWithin(directory, entry.root)) continue;
    const kind = entry.name === 'history' ? 'conda' : 'python-venv';
    byDirectory.set(directory, { root: entry.root, directory, marker: entry.absolute, kind });
  }
  return [...byDirectory.values()].map(item => {
    const interpreterCandidates = process.platform === 'win32'
      ? [path.join(item.directory, 'Scripts', 'python.exe'), path.join(item.directory, 'python.exe')]
      : [path.join(item.directory, 'bin', 'python'), path.join(item.directory, 'python')];
    const interpreter = interpreterCandidates.find(candidate => { try { return fs.statSync(candidate).isFile(); } catch { return false; } }) || null;
    let modified = null; try { modified = fs.statSync(item.marker).mtime.toISOString(); } catch { /* unavailable */ }
    let pythonVersion = null;
    try {
      const markerText = fs.readFileSync(item.marker, 'utf8').slice(0, 256 * 1024);
      const versionMatch = item.kind === 'python-venv' ? markerText.match(/^version(?:_info)?\s*=\s*([^\r\n]+)/mi) : markerText.match(/(?:^|\s)python-(\d+\.\d+(?:\.\d+)?)-/m);
      pythonVersion = cleanText(versionMatch?.[1], 80) || null;
    } catch { /* marker version unavailable */ }
    const activeEvidence = activeCandidates.filter(candidate => candidate === item.directory || candidate === interpreter || isWithin(candidate, item.directory));
    const expectedSeries = pythonVersion?.match(/\d+\.\d+/)?.[0] || null; const currentSeries = String(options.currentPythonVersion || '').match(/\d+\.\d+/)?.[0] || null;
    const versionCompatibility = expectedSeries && currentSeries ? (expectedSeries === currentSeries ? 'matching' : 'mismatched') : 'unknown';
    const packageNames = tree.entries.filter(entry => entry.directory && isWithin(entry.absolute, item.directory) && /\.dist-info$/i.test(entry.name)).map(entry => entry.name.replace(/\.dist-info$/i, '').replace(/-[^-]+$/, '')).sort();
    const ownerFiles = new Set(tree.entries.filter(entry => entry.root === item.root && entry.depth <= 2 && entry.file).map(entry => entry.name.toLowerCase()));
    const managerHints = item.kind === 'conda' ? ['conda'] : [ownerFiles.has('poetry.lock') ? 'poetry' : null, ownerFiles.has('pipfile') ? 'pipenv' : null, ownerFiles.has('uv.lock') ? 'uv' : null, 'python-venv'].filter(Boolean);
    const stale = modified && Date.now() - Date.parse(modified) > 180 * 24 * 60 * 60 * 1000;
    const state = activeEvidence.length && versionCompatibility === 'mismatched' ? 'wrong-version' : activeEvidence.length ? 'active' : !interpreter ? 'broken' : stale ? 'stale' : 'inactive';
    return {
      id: `python-env:${sha(item.directory).slice(0, 20)}`, kind: item.kind,
      path: item.directory, relative_path: path.relative(item.root, item.directory).split(path.sep).join('/') || '.', owner_root: item.root,
      interpreter, python_version: pythonVersion, state, active: state === 'active', evidence: {
        marker: path.relative(item.root, item.marker).split(path.sep).join('/'), interpreter_exists: Boolean(interpreter),
        active_signals: activeEvidence.map(candidate => candidate === options.pythonPath ? 'configured-python-path' : candidate === process.env.VIRTUAL_ENV ? 'VIRTUAL_ENV' : candidate === process.env.CONDA_PREFIX ? 'CONDA_PREFIX' : 'path-contained'),
        last_marker_change_utc: modified, stale_threshold_days: 180,
        declared_python_series: expectedSeries, observed_python_series: currentSeries, version_compatibility: versionCompatibility,
        active_evidence_captured_utc: options.generatedUtc || new Date().toISOString(), active_evidence_ttl_seconds: DEFAULT_DISCOVERY_TTL_MS / 1000
      },
      managers: managerHints, package_summary: { count: packageNames.length, samples: packageNames.slice(0, 50), completeness: tree.capped ? 'partial' : 'bounded-marker-scan' },
      lifecycle: { maintainable: true, deletion_requires_inactive_revalidation_and_explicit_confirmation: true },
      trust: { state: 'detected-not-admitted', execution_authorized: false }
    };
  }).sort((a, b) => a.path.localeCompare(b.path));
}

function secretLikeKey(key) {
  return /(SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CLIENT_SECRET|CREDENTIAL|AUTH)/i.test(key);
}

function providerForKey(key) {
  const match = String(key).match(/^(OPENAI|AZURE_OPENAI|ANTHROPIC|GOOGLE|GEMINI|OLLAMA|SUPABASE|AWS|AZURE|GITHUB|NPM|DOCKER)_/i);
  return match ? match[1].toLowerCase().replace('_', '-') : null;
}

function envIgnoreEvidence(root, relativePath) {
  const ignore = path.join(root, '.gitignore');
  let text = '';
  try { text = fs.readFileSync(ignore, 'utf8'); } catch { return { status: 'unknown', reason: 'root-.gitignore-unavailable', method: 'bounded-local-pattern-check' }; }
  const normalized = relativePath.replaceAll('\\', '/');
  const basename = path.posix.basename(normalized);
  const patterns = text.split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#') && !line.startsWith('!'));
  const matched = patterns.find(pattern => pattern === '.env' || pattern === '.env.*' || pattern === '*.env' || pattern.replace(/^\//, '') === normalized || pattern.replace(/^\*\*\//, '') === basename);
  return matched ? { status: 'ignore-pattern-observed', pattern: matched, method: 'bounded-local-pattern-check', definitive: false }
    : { status: 'potentially-exposed', reason: 'no-matching-root-ignore-pattern-observed', method: 'bounded-local-pattern-check', definitive: false };
}

function environmentFileInventory(tree) {
  const envEntries = tree.entries.filter(entry => entry.file && /^\.env(?:\..+)?$/i.test(entry.name));
  const sourceEntries = tree.entries.filter(entry => entry.file && !/^\.env(?:\..+)?$/i.test(entry.name) && /\.(?:js|cjs|mjs|ts|tsx|jsx|py|json|ya?ml|toml|ini|cfg|md)$/i.test(entry.name));
  const consumers = new Map();
  const parsed = envEntries.map(entry => {
    let raw = ''; let stat;
    try { stat = fs.statSync(entry.absolute); if (stat.size > MAX_ENV_FILE_BYTES) throw new Error('oversized'); raw = fs.readFileSync(entry.absolute, 'utf8'); }
    catch (error) { return { entry, error: error.message, keys: [] }; }
    const keys = []; const seen = new Set(); const duplicates = [];
    for (const line of raw.split(/\r?\n/)) {
      const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/); if (!match) continue;
      if (seen.has(match[1])) { duplicates.push(match[1]); continue; }
      seen.add(match[1]); keys.push(match[1]);
    }
    return { entry, stat, keys, duplicates };
  });
  const allKeys = new Set(parsed.flatMap(item => item.keys));
  for (const source of sourceEntries.slice(0, 5000)) {
    let stat; let text;
    try { stat = fs.statSync(source.absolute); if (stat.size > 512 * 1024) continue; text = fs.readFileSync(source.absolute, 'utf8'); } catch { continue; }
    for (const key of allKeys) if (new RegExp(`\\b${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(text)) {
      if (!consumers.has(key)) consumers.set(key, []);
      if (consumers.get(key).length < 25) consumers.get(key).push({ root: source.root, path: source.relative });
    }
  }
  const records = parsed.map(item => {
    const relative = item.entry.relative;
    const variables = item.keys.map(key => ({
      name: key, required: /(?:example|sample|template)$/i.test(item.entry.name), optional: !/(?:example|sample|template)$/i.test(item.entry.name),
      present: !/(?:example|sample|template)$/i.test(item.entry.name), secret_like: secretLikeKey(key),
      provider: providerForKey(key), provider_relationship: providerForKey(key) ? { provider: providerForKey(key), status: 'candidate-name-match-not-approved' } : null,
      consumers: consumers.get(key) || [], value_storage: 'prohibited', value_fingerprint: null
    }));
    return {
      id: `env-file:${sha(`${item.entry.root}\0${relative}`).slice(0, 20)}`, path: item.entry.absolute, relative_path: relative,
      owner_root: item.entry.root, kind: /(?:example|sample|template)$/i.test(item.entry.name) ? 'schema-template' : 'local-environment',
      readable: !item.error, error: item.error || null, size_bytes: item.stat?.size ?? null, modified_utc: item.stat?.mtime?.toISOString() || null,
      variable_count: variables.length, variables, exposure: envIgnoreEvidence(item.entry.root, relative),
      validation: { status: item.error ? 'unreadable' : 'pending-scope-comparison', missing_required: [], duplicate_keys: item.duplicates || [], potential_conflicts: [] },
      change_detection: { method: 'metadata-only', content_fingerprint: null, note: 'No value or plain secret hash is retained; keyed HMAC requires a separately approved secret key.' },
      lifecycle: { maintainable: true, deletion_requires_explicit_confirmation: true }
    };
  }).sort((a, b) => a.path.localeCompare(b.path));
  for (const record of records) {
    const scope = path.dirname(record.path);
    const peers = records.filter(peer => path.dirname(peer.path) === scope);
    const required = new Set(peers.filter(peer => peer.kind === 'schema-template').flatMap(peer => peer.variables.map(variable => variable.name)));
    const present = new Set(peers.filter(peer => peer.kind === 'local-environment').flatMap(peer => peer.variables.map(variable => variable.name)));
    for (const variable of record.variables) { variable.required = required.has(variable.name); variable.optional = !variable.required; }
    record.validation.missing_required = [...required].filter(key => !present.has(key)).sort();
    const counts = new Map(); for (const peer of peers.filter(item => item.kind === 'local-environment')) for (const variable of peer.variables) counts.set(variable.name, Number(counts.get(variable.name) || 0) + 1);
    record.validation.potential_conflicts = [...counts].filter(([, count]) => count > 1).map(([key, count]) => ({ key, declarations: count, values_compared: false }));
    record.validation.status = record.error ? 'unreadable' : record.validation.missing_required.length || record.validation.duplicate_keys.length ? 'attention' : 'valid-metadata';
  }
  return records;
}
function semanticGraph(subjects) {
  const nodes = [];
  const edges = [];
  const nodeIds = new Set();
  const addNode = (id, type, label, properties = {}) => { if (!nodeIds.has(id)) { nodeIds.add(id); nodes.push({ id, type, label, properties }); } };
  const addEdge = (from, predicate, to, properties = {}) => edges.push({ id: sha(`${from}\0${predicate}\0${to}`).slice(0, 24), from, predicate, to, properties });
  const addContract = (resourceId, contract = {}) => {
    for (const capability of contract.capabilities || []) { const id = `capability:${sha(String(capability)).slice(0, 20)}`; addNode(id, 'capability', String(capability)); addEdge(resourceId, 'has-capability', id); }
    for (const interfaceItem of Array.isArray(contract.interface) ? contract.interface : [contract.interface].filter(Boolean)) { const id = `interface:${sha(String(interfaceItem)).slice(0, 20)}`; addNode(id, 'interface', String(interfaceItem)); addEdge(resourceId, 'has-interface', id); }
    const requirements = typeof contract.requirements === 'string' ? [contract.requirements] : Array.isArray(contract.requirements) ? contract.requirements : Object.entries(contract.requirements || {}).map(([key, value]) => `${key}:${JSON.stringify(value)}`);
    for (const requirement of requirements) { const id = `requirement:${sha(String(requirement)).slice(0, 20)}`; addNode(id, 'requirement', String(requirement)); addEdge(resourceId, 'requires', id); }
    for (const effect of contract.effects || []) { const id = `effect:${sha(String(effect)).slice(0, 20)}`; addNode(id, 'effect', String(effect)); addEdge(resourceId, 'may-effect', id); }
    for (const conflict of contract.conflicts || []) { const label = typeof conflict === 'string' ? conflict : JSON.stringify(conflict); const id = `conflict:${sha(label).slice(0, 20)}`; addNode(id, 'conflict', label); addEdge(resourceId, 'conflicts-with', id); }
    if (contract.policy) { const id = `policy:${sha(String(contract.policy)).slice(0, 20)}`; addNode(id, 'policy', String(contract.policy)); addEdge(resourceId, 'governed-by', id); }
    if (contract.state) { const id = `state:${sha(String(contract.state)).slice(0, 20)}`; addNode(id, 'resource-state', String(contract.state)); addEdge(resourceId, 'has-state', id); }
  };
  addNode('px:orchestration-plane', 'orchestration-plane', 'Pacify-X orchestration plane', { authority: 'project-owned capability map' });
  for (const extension of subjects.extensions) {
    const extensionId = `vscode-extension:${extension.id}`; addNode(extensionId, 'vscode-extension', extension.name, { version: extension.version, active: extension.active, integration_status: extension.integration_status });
    addEdge(extensionId, 'available-to', 'px:orchestration-plane');
    for (const point of extension.contribution_points) { const pointId = `vscode-contribution:${point}`; addNode(pointId, 'vscode-contribution-point', point); addEdge(extensionId, 'contributes', pointId); }
    for (const command of extension.commands) { const commandId = `vscode-command:${command.id}`; addNode(commandId, 'vscode-command', command.id, { invocation: command.invocation, expected_inputs: command.expected_inputs, expected_outputs: command.expected_outputs }); addEdge(extensionId, 'contributes-command', commandId); addEdge(commandId, 'available-to', 'px:orchestration-plane'); }
    for (const dependency of extension.dependencies) { const dependencyId = `vscode-extension:${dependency}`; addNode(dependencyId, 'vscode-extension-reference', dependency); addEdge(extensionId, 'depends-on', dependencyId); }
    addContract(extensionId, extension.resource_contract);
  }
  for (const tool of subjects.system_tools) {
    const toolId = `system-tool:${tool.id}`; addNode(toolId, 'system-tool', tool.id, { available: tool.available, version: tool.version });
    if (tool.available) addEdge(toolId, 'available-to', 'px:orchestration-plane');
    addContract(toolId, tool.resource_contract);
  }
  for (const packageItem of [...subjects.python_packages, ...subjects.npm_global_packages, ...subjects.npm_project_packages]) {
    const packageId = `package:${packageItem.manager}:${packageItem.scope}:${packageItem.name}`;
    const managerId = packageItem.manager === 'python-pip' ? 'system-tool:python' : 'system-tool:npm';
    addNode(packageId, 'installed-package', packageItem.name, { version: packageItem.version, manager: packageItem.manager, scope: packageItem.scope });
    addEdge(packageId, 'installed-by', managerId); addEdge(packageId, 'available-to', 'px:orchestration-plane');
    addContract(packageId, packageItem.resource_contract);
  }
  for (const environment of subjects.virtual_environments || []) {
    const environmentId = environment.id; const rootId = `root:${sha(environment.owner_root).slice(0, 20)}`;
    addNode(rootId, 'admitted-root', path.basename(environment.owner_root), { path: environment.owner_root });
    addNode(environmentId, 'virtual-environment', environment.relative_path, { kind: environment.kind, state: environment.state, active: environment.active });
    addEdge(environmentId, 'owned-by-root', rootId);
    if (environment.interpreter) addEdge(environmentId, 'uses-tool', 'system-tool:python');
    addContract(environmentId, environment.resource_contract);
  }
  for (const environmentFile of subjects.environment_files || []) {
    addNode(environmentFile.id, 'environment-file', environmentFile.relative_path, { kind: environmentFile.kind, readable: environmentFile.readable, exposure: environmentFile.exposure.status });
    for (const variable of environmentFile.variables || []) {
      const variableId = `environment-variable:${sha(variable.name).slice(0, 20)}`;
      addNode(variableId, 'environment-variable-schema', variable.name, { secret_like: variable.secret_like, provider: variable.provider, value_storage: 'prohibited' });
      addEdge(environmentFile.id, 'declares-variable', variableId);
      for (const consumer of variable.consumers || []) {
        const consumerId = `file:${sha(`${consumer.root}\0${consumer.path}`).slice(0, 20)}`;
        addNode(consumerId, 'consumer-file', consumer.path, { root: consumer.root });
        addEdge(consumerId, 'consumes-variable', variableId, { path: consumer.path });
      }
    }
  }
  nodes.sort((a, b) => a.id.localeCompare(b.id)); edges.sort((a, b) => a.id.localeCompare(b.id));
  return { nodes, edges };
}
function buildInventory({ extensions = [], tools = [], packages = {}, virtualEnvironments = [], environmentFiles = [], scan = {}, generatedUtc = new Date().toISOString() }) {
  const packageContract = item => ({
    ...item,
    resource_contract: { resource: `${item.manager}:${item.scope}:${item.name}`, capabilities: ['installed-package'], interface: item.manager, requirements: [`${item.manager} package environment`], effects: ['available-for-separately-governed-invocation'], conflicts: [], policy: 'detected-read-only-not-admitted-for-automatic-execution', state: 'installed' }
  });
  const subjects = {
    extensions: normalizeExtensions(extensions).map(item => ({ ...item, resource_contract: { resource: item.id, capabilities: item.capabilities.map(capability => capability.id), interface: item.commands.map(command => command.id), requirements: item.permissions_resources, effects: ['metadata-read-only; invocation effects remain provider-owned'], conflicts: item.known_conflicts, policy: 'detect-without-activation; invoke-only-through-separate-governed action', state: item.active ? 'active-in-host' : 'installed-not-active' } })),
    system_tools: tools.map(item => ({ ...item, resource_contract: { resource: item.id, capabilities: item.capabilities || (item.available ? ['version-probed'] : []), interface: `${item.command} ${item.probe}`, requirements: [...(item.dependencies || []), ...(item.environment_requirements || [])], effects: ['probe-read-only'], conflicts: item.conflicts || [], policy: 'no shell; fixed argument probe; provider keys stripped; invocation requires separate admission', state: item.available ? item.health || 'available' : 'absent' } })),
    python_packages: (packages.python || []).map(packageContract), npm_global_packages: (packages.npm_global || []).map(packageContract), npm_project_packages: (packages.npm_project || []).map(packageContract),
    virtual_environments: virtualEnvironments.map(item => ({ ...item, resource_contract: { resource: item.id, capabilities: ['isolated-python-environment'], interface: item.interpreter || 'interpreter-unavailable', requirements: ['bounded admitted root'], effects: ['read-only metadata discovery'], conflicts: item.state === 'broken' ? ['interpreter-missing'] : [], policy: 'execution and deletion require separate admission', state: item.state } })),
    environment_files: environmentFiles
  };
  const graph = semanticGraph(subjects);
  const stable = {
    schema_version: SCHEMA, authority: 'Pacify-X extension read-only environment discovery',
    boundaries: { arbitrary_extension_activation: false, credential_values_persisted: false, weak_secret_fingerprints: false, network_installs: false, billable_calls: false, mutation: false, admitted_roots_only: true },
    ontology: {
      canonical_chain: ['resource', 'capabilities', 'interface', 'requirements', 'effects', 'conflicts', 'policy', 'state'],
      node_types: ['orchestration-plane', 'admitted-root', 'consumer-file', 'vscode-extension', 'vscode-extension-reference', 'vscode-contribution-point', 'vscode-command', 'system-tool', 'installed-package', 'virtual-environment', 'environment-file', 'environment-variable-schema', 'capability', 'interface', 'requirement', 'effect', 'conflict', 'policy', 'resource-state'],
      predicates: ['has-capability', 'has-interface', 'requires', 'may-effect', 'conflicts-with', 'governed-by', 'has-state', 'available-to', 'contributes', 'contributes-command', 'depends-on', 'installed-by', 'owned-by-root', 'uses-tool', 'declares-variable', 'consumes-variable']
    }, subjects, graph,
    discovery: {
      completeness: scan.completeness || (scan.capped ? 'partial' : 'complete'), scanned_entries: (scan.entries || []).length,
      capped: Boolean(scan.capped), entry_limit: scan.limit || MAX_SCAN_ENTRIES, max_depth: scan.max_depth || MAX_SCAN_DEPTH,
      admitted_roots: scan.root_records || (scan.roots || []).map(root => ({ requested_root: root, resolved_root: root, state: 'available' })),
      failures: scan.failures || [], ambiguities: scan.ambiguities || [], symbolic_links_skipped: Number(scan.symbolic_links_skipped || 0)
    },
    summary: {
      extensions: subjects.extensions.length, active_extensions: subjects.extensions.filter(item => item.active).length,
      system_tools: subjects.system_tools.length, available_tools: subjects.system_tools.filter(item => item.available).length,
      python_packages: subjects.python_packages.length, npm_global_packages: subjects.npm_global_packages.length, npm_project_packages: subjects.npm_project_packages.length,
      virtual_environments: subjects.virtual_environments.length, active_virtual_environments: subjects.virtual_environments.filter(item => item.active).length,
      environment_files: subjects.environment_files.length, environment_variables: subjects.environment_files.reduce((sum, item) => sum + item.variable_count, 0),
      environment_scan_capped: Boolean(scan.capped), admitted_roots: (scan.roots || []).length,
      graph_nodes: graph.nodes.length, graph_edges: graph.edges.length
    }
  };
  return { ...stable, generated_utc: generatedUtc, snapshot_hash: sha(stable) };
}
function pathsFor(projectRoot) {
  const root = path.join(path.resolve(projectRoot), '.engineering-bootstrap', 'environment');
  return { root, current: path.join(root, 'current.json'), events: path.join(root, 'events.jsonl'), snapshots: path.join(root, 'snapshots') };
}
function optionalCurrentPathFor(projectRoot) {
  return projectRoot ? pathsFor(projectRoot).current : '';
}
function atomicWrite(target, value) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  try { fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' }); fs.renameSync(temporary, target); }
  finally { try { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); } catch {} }
}
function readEnvironmentInventory(projectRoot) {
  const paths = pathsFor(projectRoot);
  try {
    let inventory = JSON.parse(fs.readFileSync(paths.current, 'utf8'));
    const stable = compactStable(inventory);
    if (![SCHEMA, LEGACY_SCHEMA].includes(inventory.schema_version) || inventory.snapshot_hash !== sha(stable)) throw new Error('Environment inventory integrity failed.');
    if (inventory.schema_version === LEGACY_SCHEMA) inventory = migrateLegacyInventory(inventory);
    const captured = Date.parse(inventory.discovery?.captured_utc || inventory.generated_utc || '');
    const expires = Date.parse(inventory.discovery?.expires_utc || ''); const now = Date.now();
    inventory.freshness = {
      state: Number.isFinite(expires) ? (now <= expires ? 'fresh' : 'stale') : 'unknown',
      age_seconds: Number.isFinite(captured) ? Math.max(0, Math.floor((now - captured) / 1000)) : null,
      expires_utc: Number.isFinite(expires) ? new Date(expires).toISOString() : null,
      generation: inventory.discovery?.generation || null
    };
    return { paths, inventory };
  } catch { return { paths, inventory: null }; }
}

function compactStable(inventory) {
  const stable = { schema_version: inventory.schema_version, authority: inventory.authority, boundaries: inventory.boundaries, ontology: inventory.ontology, summary: inventory.summary, storage: inventory.storage, datasets: inventory.datasets, content_hash: inventory.content_hash };
  if (inventory.discovery) stable.discovery = inventory.discovery;
  if (inventory.migration) stable.migration = inventory.migration;
  return stable;
}

function migrateLegacyInventory(inventory) {
  const stable = {
    ...compactStable(inventory), schema_version: SCHEMA,
    boundaries: { ...inventory.boundaries, credential_values_persisted: false, weak_secret_fingerprints: false, admitted_roots_only: true },
    summary: { ...inventory.summary, virtual_environments: 0, active_virtual_environments: 0, environment_files: 0, environment_variables: 0, environment_scan_capped: false, admitted_roots: 0 },
    datasets: { ...inventory.datasets, environments: null, environment_files: null },
    migration: { from: LEGACY_SCHEMA, mode: 'in-memory-compatible-read', refresh_required_for_new_datasets: true }
  };
  return { ...stable, generated_utc: inventory.generated_utc, source_snapshot_hash: inventory.snapshot_hash, snapshot_hash: sha(stable) };
}
function writeDataset(paths, snapshotDirectory, name, value) {
  const target = path.join(snapshotDirectory, `${name}.json`); const serialized = `${JSON.stringify(value, null, 2)}\n`; const digest = sha(serialized);
  if (!fs.existsSync(target)) atomicWrite(target, value);
  const relative = path.relative(paths.root, target).split(path.sep).join('/');
  return { path: relative, sha256: digest, records: Array.isArray(value) ? value.length : undefined };
}
function readDataset(paths, descriptor) {
  if (!descriptor?.path || !descriptor.sha256) throw new Error('Environment dataset descriptor is incomplete.');
  const target = path.resolve(paths.root, descriptor.path); const relative = path.relative(paths.root, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Environment dataset path escaped its root.');
  const stat = fs.statSync(target); if (!stat.isFile() || stat.size > MAX_OUTPUT) throw new Error('Environment dataset is unavailable or oversized.');
  const serialized = fs.readFileSync(target, 'utf8'); if (sha(serialized) !== descriptor.sha256) throw new Error('Environment dataset integrity failed.');
  return JSON.parse(serialized);
}
function applyEnvironmentFreshness(records, freshness) {
  if (freshness?.state !== 'stale') return records;
  return records.map(record => record.active ? { ...record, active: false, state: 'unknown', evidence: { ...record.evidence, active_evidence_stale: true } } : record);
}
function readEnvironmentSubject(projectRoot, subject = 'summary', options = {}) {
  const loaded = readEnvironmentInventory(projectRoot); if (!loaded.inventory) return { available: false, reason: 'Environment capability map is unavailable.' };
  const inventory = loaded.inventory; if (subject === 'summary') return { available: true, inventory };
  if (!['extensions', 'tools', 'python', 'npm', 'environments', 'environment-files', 'graph'].includes(subject)) throw new Error('Unknown environment subject.');
  const observation = { snapshot_hash: inventory.snapshot_hash, generated_utc: inventory.generated_utc || null, freshness: inventory.freshness || { state: 'unknown' } };
  if (subject === 'graph') return { available: true, subject, ...observation, ontology: inventory.ontology, nodes: readDataset(loaded.paths, inventory.datasets.graph_nodes), edges: readDataset(loaded.paths, inventory.datasets.graph_edges) };
  let records;
  if (subject === 'npm') records = [...readDataset(loaded.paths, inventory.datasets.npm_global), ...readDataset(loaded.paths, inventory.datasets.npm_project)];
  else {
    const key = subject === 'environment-files' ? 'environment_files' : subject;
    records = inventory.datasets[key] ? readDataset(loaded.paths, inventory.datasets[key]) : [];
  }
  if (subject === 'environments') records = applyEnvironmentFreshness(records, inventory.freshness);
  const query = String(options.query || '').toLowerCase(); if (query) records = records.filter(item => JSON.stringify(item).toLowerCase().includes(query));
  const total = records.length; const offset = Math.max(0, Number(options.offset || 0)); const limit = Math.min(500, Math.max(1, Number(options.limit || 100)));
  return { available: true, subject, ...observation, total, offset, limit, records: records.slice(offset, offset + limit) };
}
function readEnvironmentExtension(projectRoot, extensionId) {
  const loaded = readEnvironmentInventory(projectRoot); if (!loaded.inventory) throw new Error('Environment capability map is unavailable.');
  const records = readDataset(loaded.paths, loaded.inventory.datasets.extensions);
  const record = records.find(item => item.id === extensionId); if (!record) throw new Error('Unknown environment extension.');
  return { available: true, snapshot_hash: loaded.inventory.snapshot_hash, generated_utc: loaded.inventory.generated_utc || null, freshness: loaded.inventory.freshness || { state: 'unknown' }, extension: readDataset(loaded.paths, record.detail_ref) };
}
function persistEnvironmentInventory(projectRoot, inventory, reason = 'refresh') {
  const prior = readEnvironmentInventory(projectRoot);
  let priorNodeRecords = [];
  try { priorNodeRecords = prior.inventory ? readDataset(prior.paths, prior.inventory.datasets.graph_nodes) : []; } catch { priorNodeRecords = []; }
  const priorNodes = new Set(priorNodeRecords.map(item => item.id));
  const nextNodes = new Set(inventory.graph.nodes.map(item => item.id));
  const added = [...nextNodes].filter(id => !priorNodes.has(id)); const removed = [...priorNodes].filter(id => !nextNodes.has(id));
  const snapshotDirectory = path.join(prior.paths.snapshots, inventory.snapshot_hash);
  const extensionIndex = inventory.subjects.extensions.map(item => {
    const detail = writeDataset(prior.paths, path.join(snapshotDirectory, 'extensions'), sha(item.id), item);
    return { id: item.id, name: item.name, version: item.version, publisher: item.publisher, active: item.active, builtin: item.builtin, integration_status: item.integration_status, capability_count: item.capabilities.length, command_count: item.commands.length, conflict_count: item.known_conflicts.length, contribution_points: item.contribution_points, detail_ref: detail };
  });
  const datasets = {
    extensions: writeDataset(prior.paths, snapshotDirectory, 'extensions-index', extensionIndex),
    tools: writeDataset(prior.paths, snapshotDirectory, 'system-tools', inventory.subjects.system_tools),
    python: writeDataset(prior.paths, snapshotDirectory, 'python-packages', inventory.subjects.python_packages),
    npm_global: writeDataset(prior.paths, snapshotDirectory, 'npm-global-packages', inventory.subjects.npm_global_packages),
    npm_project: writeDataset(prior.paths, snapshotDirectory, 'npm-project-packages', inventory.subjects.npm_project_packages),
    environments: writeDataset(prior.paths, snapshotDirectory, 'virtual-environments', inventory.subjects.virtual_environments),
    environment_files: writeDataset(prior.paths, snapshotDirectory, 'environment-files', inventory.subjects.environment_files),
    graph_nodes: writeDataset(prior.paths, snapshotDirectory, 'graph-nodes', inventory.graph.nodes),
    graph_edges: writeDataset(prior.paths, snapshotDirectory, 'graph-edges', inventory.graph.edges)
  };
  const capturedUtc = new Date().toISOString(); const generation = Number(prior.inventory?.discovery?.generation || 0) + 1;
  const discovery = {
    ...inventory.discovery, generation, captured_utc: capturedUtc,
    expires_utc: new Date(Date.parse(capturedUtc) + DEFAULT_DISCOVERY_TTL_MS).toISOString(), ttl_seconds: DEFAULT_DISCOVERY_TTL_MS / 1000,
    content_fingerprint: inventory.snapshot_hash, previous_snapshot_hash: prior.inventory?.snapshot_hash || null,
    changed_from_previous: prior.inventory?.content_hash !== inventory.snapshot_hash
  };
  const stable = {
    schema_version: SCHEMA, authority: inventory.authority, boundaries: inventory.boundaries, ontology: inventory.ontology, summary: inventory.summary,
    storage: { mode: 'compact-index-with-hash-verified-lazy-shards', snapshot_directory: path.relative(prior.paths.root, snapshotDirectory).split(path.sep).join('/'), per_extension_contracts: true },
    datasets, content_hash: inventory.snapshot_hash, discovery
  };
  const compact = { ...stable, generated_utc: inventory.generated_utc, snapshot_hash: sha(stable) };
  atomicWrite(prior.paths.current, compact);
  const event = {
    schema_version: 'px.environment-capability-event/1.0', event_id: `env-${crypto.randomUUID()}`, timestamp: new Date().toISOString(), reason,
    previous_hash: prior.inventory?.snapshot_hash || null, snapshot_hash: compact.snapshot_hash, added_node_ids: added.slice(0, 5000), removed_node_ids: removed.slice(0, 5000),
    changed: prior.inventory?.content_hash !== inventory.snapshot_hash, generation,
    completeness: discovery.completeness, failure_count: discovery.failures.length, ambiguity_count: discovery.ambiguities.length
  };
  fs.mkdirSync(prior.paths.root, { recursive: true }); fs.appendFileSync(prior.paths.events, `${JSON.stringify(event)}\n`, 'utf8');
  return {
    paths: prior.paths,
    inventory: { ...compact, freshness: { state: 'fresh', age_seconds: 0, expires_utc: discovery.expires_utc, generation } },
    event
  };
}
async function discoverEnvironment({ extensions = [], projectRoot, engineRoot, pythonPath = 'python', run = runBounded, reason = 'refresh', signal, persist = true }) {
  const roots = admittedRoots([projectRoot, engineRoot]);
  const governedRun = (command, args, options = {}) => run(command, args, { ...options, signal });
  const toolsPromise = toolInventory(governedRun, pythonPath);
  const packagesPromise = packageInventory(governedRun, pythonPath, projectRoot);
  const tools = await toolsPromise;
  const scanPromise = scanEnvironmentAsync(roots, {
    pythonPath,
    currentPythonVersion: tools.find(item => item.id === 'python')?.version || null,
    generatedUtc: new Date().toISOString(), signal
  });
  const [packages, scanResult] = await Promise.all([packagesPromise, scanPromise]);
  if (signal?.aborted) { const error = new Error('Environment discovery cancelled.'); error.name = 'AbortError'; throw error; }
  const { tree, virtualEnvironments, environmentFiles } = scanResult;
  const inventory = buildInventory({ extensions, tools, packages, virtualEnvironments, environmentFiles, scan: tree });
  if (persist) return persistEnvironmentInventory(projectRoot, inventory, reason);
  return {
    paths: pathsFor(projectRoot),
    inventory: { ...inventory, freshness: { state: 'memory-current', age_seconds: 0, generation: null } },
    event: null,
    persistence: 'memory-only-read-discovery'
  };
}

module.exports = {
  SCHEMA, LEGACY_SCHEMA, TOOL_PROBES, runBounded, normalizeExtensions, toolInventory, packageInventory, semanticGraph,
  admittedRoots, rootIdentity, inspectRoots, boundedTree, scanEnvironmentAsync, virtualEnvironmentInventory, environmentFileInventory, migrateLegacyInventory,
  buildInventory, pathsFor, optionalCurrentPathFor, readEnvironmentInventory, applyEnvironmentFreshness, readEnvironmentSubject, readEnvironmentExtension, persistEnvironmentInventory, discoverEnvironment
};
