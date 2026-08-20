'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { processTreeSpawnOptions, terminateProcessTree } = require('./processTree');

const GIT_MUTATION_PROHIBITIONS = Object.freeze([
  'commit', 'push', 'pull', 'fetch', 'merge', 'rebase', 'cherry-pick', 'revert',
  'reset', 'checkout', 'switch', 'restore', 'stash', 'clean', 'tag', 'branch mutation'
]);
const BILLABLE_PROVIDER_ENVIRONMENT_KEYS = Object.freeze([
  'OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY',
  'GEMINI_API_KEY', 'CODEX_API_KEY', 'MISTRAL_API_KEY', 'COHERE_API_KEY',
  'GROQ_API_KEY', 'TOGETHER_API_KEY', 'OPENROUTER_API_KEY', 'PERPLEXITY_API_KEY',
  'XAI_API_KEY', 'DEEPSEEK_API_KEY'
]);

function nonBillableEnvironment(source = process.env) {
  const denied = new Set(BILLABLE_PROVIDER_ENVIRONMENT_KEYS);
  const result = {};
  for (const [key, value] of Object.entries(source)) if (!denied.has(key.toUpperCase())) result[key] = value;
  return result;
}

function capture(command, args, options = {}) {
  return new Promise(resolve => {
    const child = cp.spawn(command, args, {
      cwd: options.cwd,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...processTreeSpawnOptions(),
      env: { ...(options.env || nonBillableEnvironment()) }
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; terminateProcessTree(child); }, options.timeoutMs || 5000);
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { stdout = (stdout + chunk).slice(-200000); });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-80000); });
    child.on('error', error => { clearTimeout(timer); resolve({ ok: false, code: null, stdout, stderr, error: error.message, timedOut }); });
    child.on('close', code => { clearTimeout(timer); resolve({ ok: code === 0 && !timedOut, code, stdout, stderr, error: null, timedOut }); });
  });
}

async function gitSnapshot(workspaceRoot, maxChanges = 200) {
  if (!workspaceRoot) return { available: false, reason: 'No workspace root.', operation: 'none', changes: [] };
  const rootResult = await capture('git', ['-C', workspaceRoot, 'rev-parse', '--show-toplevel'], { timeoutMs: 5000 });
  if (!rootResult.ok) return { available: false, reason: 'Workspace is not an accessible Git repository.', operation: 'none', changes: [] };
  const repositoryRoot = path.resolve(rootResult.stdout.trim());
  const status = await capture('git', ['-C', repositoryRoot, 'status', '--porcelain=v2', '--branch', '--untracked-files=normal'], { timeoutMs: 10000 });
  if (!status.ok) return { available: false, reason: status.stderr.trim() || 'Git status failed.', repositoryRoot, operation: 'unknown', changes: [] };
  const gitDirResult = await capture('git', ['-C', repositoryRoot, 'rev-parse', '--absolute-git-dir'], { timeoutMs: 5000 });
  const gitDir = gitDirResult.ok ? path.resolve(gitDirResult.stdout.trim()) : undefined;
  const result = {
    available: true, repositoryRoot, gitDir, branch: null, head: null, upstream: null,
    ahead: 0, behind: 0, operation: detectGitOperation(gitDir), changes: [],
    staged: 0, unstaged: 0, untracked: 0, capped: false
  };
  for (const line of status.stdout.split(/\r?\n/)) {
    if (line.startsWith('# branch.oid ')) result.head = line.slice(13).trim();
    else if (line.startsWith('# branch.head ')) result.branch = line.slice(14).trim();
    else if (line.startsWith('# branch.upstream ')) result.upstream = line.slice(18).trim();
    else if (line.startsWith('# branch.ab ')) {
      const match = line.match(/\+(\d+)\s+-(\d+)/); if (match) { result.ahead = Number(match[1]); result.behind = Number(match[2]); }
    } else if (line.startsWith('? ')) {
      result.untracked += 1;
      if (result.changes.length < maxChanges) result.changes.push({ path: line.slice(2), index: '?', worktree: '?', kind: 'untracked' }); else result.capped = true;
    } else if (/^[12u] /.test(line)) {
      const fields = line.split(' ');
      const xy = fields[1] || '..';
      const fieldCount = line.startsWith('1 ') ? 8 : line.startsWith('2 ') ? 9 : 10;
      const file = fields.slice(fieldCount).join(' ').split('\t')[0];
      if (xy[0] && xy[0] !== '.') result.staged += 1;
      if (xy[1] && xy[1] !== '.') result.unstaged += 1;
      if (result.changes.length < maxChanges) result.changes.push({ path: file, index: xy[0], worktree: xy[1], kind: line[0] }); else result.capped = true;
    }
  }
  result.dirty = result.staged + result.unstaged + result.untracked > 0;
  result.conflicts = result.changes.filter(change => change.kind === 'u').length;
  return result;
}

function detectGitOperation(gitDir) {
  if (!gitDir) return 'unknown';
  const checks = [
    ['MERGE_HEAD', 'merge'], ['CHERRY_PICK_HEAD', 'cherry-pick'], ['REVERT_HEAD', 'revert'],
    ['rebase-merge', 'rebase'], ['rebase-apply', 'rebase'], ['BISECT_LOG', 'bisect']
  ];
  for (const [marker, operation] of checks) if (fs.existsSync(path.join(gitDir, marker))) return operation;
  return 'none';
}

function gitConflictDecision(snapshot, bridgeRunActive = false) {
  const reasons = [];
  if (!snapshot?.available) reasons.push('git-unavailable');
  if (snapshot?.operation && snapshot.operation !== 'none') reasons.push(`git-operation-active:${snapshot.operation}`);
  if (snapshot?.conflicts) reasons.push(`unmerged-paths:${snapshot.conflicts}`);
  if (bridgeRunActive) reasons.push('bridge-codex-run-active');
  return { allowed: reasons.length === 0, reasons, warnings: snapshot?.dirty ? [`dirty-worktree:${snapshot.staged || 0}/${snapshot.unstaged || 0}/${snapshot.untracked || 0}`] : [] };
}

async function providerStatus(workspaceRoot) {
  const [codex, login, git] = await Promise.all([
    capture('codex', ['--version'], { cwd: workspaceRoot, timeoutMs: 5000 }),
    capture('codex', ['login', 'status'], { cwd: workspaceRoot, timeoutMs: 5000 }),
    capture('git', ['--version'], { cwd: workspaceRoot, timeoutMs: 5000 })
  ]);
  const loginText = `${login.stdout}\n${login.stderr}`;
  const authenticationChannel = /logged in using chatgpt/i.test(loginText) ? 'ChatGPT (verified by Codex CLI)' : login.ok ? 'Codex CLI authenticated; channel not identified' : 'Not verified';
  return {
    contextSource: 'VS Code + Pacify-X + read-only Git snapshot',
    executor: codex.ok ? 'OpenAI Codex CLI available' : 'Codex CLI unavailable',
    authenticationIdentity: authenticationChannel,
    billingIdentity: 'Not exposed by supported CLI/API; never inferred',
    model: 'Selected by Codex configuration at execution time',
    session: 'Bridge runs are explicit and ephemeral',
    handoffLevel: 'Level 2 - portable context snapshot',
    nativeSessionTransfer: 'Unsupported; fails closed',
    codexVersion: codex.ok ? codex.stdout.trim() : null,
    gitVersion: git.ok ? git.stdout.trim() : null,
    gitAuthority: 'Git owns repository state; bridge forbids Git mutations',
    chatGptAuthenticated: /logged in using chatgpt/i.test(loginText),
    billableApiCredentialsForwarded: false
  };
}

async function buildContextEnvelope(input) {
  const git = await gitSnapshot(input.workspaceRoot);
  const files = [...new Set((input.openFiles || []).filter(Boolean).map(file => path.resolve(file)).filter(file => isWithin(file, [input.workspaceRoot])))];
  const envelope = {
    schema_version: '2.0',
    created_utc: new Date().toISOString(),
    correlation_id: crypto.randomUUID(),
    objective: String(input.objective || '').slice(0, 12000),
    source: { surface: input.sourceSurface || 'VS Code', provider: 'Pacify-X extension', session_id: input.sourceSessionId || null },
    context: {
      workspace: input.workspaceRoot || null,
      engine_root: input.engineRoot || null,
      active_file: input.activeFile && isWithin(input.activeFile, [input.workspaceRoot]) ? path.relative(input.workspaceRoot, input.activeFile) : null,
      open_files: files.slice(0, 50).map(file => path.relative(input.workspaceRoot, file)),
      instruction_refs: ['AGENTS.md'],
      memory_refs: input.coordination?.paths ? [
        relativeReference(input.workspaceRoot, input.coordination.paths.handoff_json),
        relativeReference(input.workspaceRoot, input.coordination.paths.state),
        relativeReference(input.workspaceRoot, input.coordination.paths.memory_root)
      ].filter(Boolean) : [],
      tool_result_refs: (input.coordination?.events || []).slice(-10).map(event => event.event_id).filter(Boolean),
      context_injection_cap_tokens: Number(input.contextCapTokens || 12000),
      file_contents_included: false, credentials_included: false
    },
    git,
    git_policy: {
      authority: 'Git/VS Code Source Control', mutation_allowed: false,
      prohibited_operations: GIT_MUTATION_PROHIBITIONS,
      rule: 'Read Git state for context. Never commit, reset, checkout, stash, merge, rebase, tag, fetch, pull, push, or clean. Preserve all pre-existing changes.'
    },
    target: {
      executor: input.executor || 'OpenAI Codex CLI', provider: 'OpenAI',
      authentication_identity: input.authenticationIdentity || null,
      billing_identity: null, model: null, session_id: null,
      sandbox: input.sandbox || 'read-only',
      billable_api_credentials_allowed: false
    },
    continuity: input.coordination ? {
      source: 'project-owned Pacify-X coordination ledger',
      state_hash: input.coordination.state?.state_hash || null,
      active_plan: input.coordination.state?.active_plan || null,
      active_claims: input.coordination.state?.claims || [],
      task_states: (input.coordination.state?.tasks || []).map(task => ({ id: task.id, title: task.title, status: task.status, depends_on: task.depends_on, owner: task.owner, claim_targets: task.claim_targets })),
      handoff_ref: relativeReference(input.workspaceRoot, input.coordination.paths?.handoff_json),
      event_log_ref: relativeReference(input.workspaceRoot, input.coordination.paths?.events),
      canonical_memory_mutated: false
    } : null
  };
  envelope.sha256 = crypto.createHash('sha256').update(JSON.stringify(envelope)).digest('hex');
  return envelope;
}

function relativeReference(root, candidate) {
  if (!root || !candidate || !isWithin(candidate, [root])) return null;
  return path.relative(root, candidate).split(path.sep).join('/');
}

function isWithin(candidate, roots) {
  if (!candidate) return false;
  const resolved = path.resolve(candidate);
  return roots.filter(Boolean).some(root => { const relative = path.relative(path.resolve(root), resolved); return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative)); });
}

function codexPrompt(envelope) {
  return [
    'You are receiving a governed Pacify-X portable context handoff.',
    'Honor AGENTS.md and all repository-local instructions.',
    'Git is the canonical repository-state authority. Do not run any Git mutation operation, including commit, push, pull, fetch, merge, rebase, cherry-pick, revert, reset, checkout, switch, restore, stash, clean, tag, or branch mutation.',
    'Inspect and preserve every pre-existing working-tree change. Never overwrite or attribute changes you did not create.',
    'Read the Pacify-X coordination handoff and active claims before editing. For workspace writes, operate only inside the task claim assigned to this actor/session. Stop on any overlapping or stale claim.',
    'Record progress, evidence, failures, and the exact next action in the project-owned Pacify-X coordination ledger before handoff.',
    'Use only the sandbox and workspace effects granted by this invocation. Report unsupported or blocked actions explicitly.',
    `Portable context envelope:\n${JSON.stringify(envelope, null, 2)}`
  ].join('\n\n');
}

module.exports = { capture, gitSnapshot, detectGitOperation, gitConflictDecision, providerStatus, buildContextEnvelope, codexPrompt, GIT_MUTATION_PROHIBITIONS, BILLABLE_PROVIDER_ENVIRONMENT_KEYS, nonBillableEnvironment, isWithin, relativeReference };
