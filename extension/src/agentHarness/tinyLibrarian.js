'use strict';

const { performance } = require('node:perf_hooks');
const { sha256, nowIso } = require('./ids');
const { LibrarianArtifact, parse } = require('./contracts');

function deterministicClassification(task, message) {
  const text = `${task.goal}\n${message || ''}`.toLowerCase();
  const domains = new Set(); const skills = new Set(); const queries = [];
  const has = (...terms) => terms.some(term => text.includes(term));
  let intent = 'general-engineering'; let stage = task.mode === 'IMPLEMENT' ? 'IMPLEMENT' : task.mode === 'REVIEW' ? 'REVIEW' : task.mode === 'DIAGNOSE' ? 'DIAGNOSE' : 'PLAN';
  if (has('test', 'pytest', 'hang', 'failing')) { intent = has('hang', 'stuck', 'freeze') ? 'debug-test-hang' : 'debug-test'; domains.add('testing'); skills.add('evidence-validation'); }
  if (has('.py', 'python', 'pytest')) { domains.add('python'); skills.add('repo-navigation'); }
  if (has('vscode', 'extension', 'webview')) { domains.add('vscode-extension'); skills.add('vscode-extension'); }
  if (has('api', 'provider', 'openrouter', 'codex', 'copilot', 'ollama')) { domains.add('ai-provider'); skills.add('provider-routing'); }
  if (has('git', 'diff', 'branch')) { domains.add('git'); skills.add('git-readonly'); }
  if (!domains.size) domains.add('software-engineering');
  queries.push(task.goal.slice(0, 400));
  return { intent, stage, domains: [...domains], skillCandidates: [...skills], retrievalRequired: true, retrievalQueries: queries,
    routeRecommendation: null, escalationRecommended: false, confidence: 0.62, source: 'deterministic-fallback' };
}

class PXArchivist {
  constructor(options = {}) {
    this.modelRunner = options.modelRunner || null;
    this.experienceStore = options.experienceStore || null;
    this.experiences = new Map();
  }

  async recall(task) {
    const rows = this.experienceStore?.load ? await this.experienceStore.load(task.taskId) : this.experiences.get(task.taskId);
    return (Array.isArray(rows) ? rows : []).filter(row => row.taskId === task.taskId).slice(-8)
      .map(row => ({ refId: row.recordId, kind: 'tie-experience', label: 'Prior worker experience',
        source: `task:${task.taskId}`, authority: 'unverified-operational-experience', freshAt: row.observedAt,
        content: row.content, sha256: sha256(row.content) }));
  }

  async observe(task, { runId, workerId, text, verdict }) {
    // Worker output is experience, never a validated improvement or permission.
    const content = JSON.stringify({ workerId, output: String(text || '').slice(0, 24000),
      completionSatisfied: verdict?.complete === true, authorityGranted: false });
    const row = { recordId: `tie:${sha256(`${task.taskId}:${runId}:${content}`)}`, taskId: task.taskId,
      runId, workerId, observedAt: nowIso(), content, validated: false };
    const stored = this.experienceStore?.load ? await this.experienceStore.load(task.taskId) : this.experiences.get(task.taskId);
    const rows = [...(Array.isArray(stored) ? stored : []).filter(r => r.taskId === task.taskId && r.recordId !== row.recordId), row].slice(-8);
    if (this.experienceStore?.save) await this.experienceStore.save(task.taskId, rows);
    this.experiences.set(task.taskId, rows);
    return row;
  }

  async classify(task, message) {
    const started = performance.now(); let result;
    if (this.modelRunner) {
      try {
        const candidate = await this.modelRunner({
          instruction: 'Return only structured classification fields: intent, stage, domains, skillCandidates, retrievalRequired, retrievalQueries, routeRecommendation, escalationRecommended, confidence.',
          task: { goal: task.goal, mode: task.mode, stage: task.stage, targets: task.targets }, message: String(message || '').slice(0, 12000)
        });
        result = { ...candidate, source: 'tiny-model' };
      } catch { result = deterministicClassification(task, message); }
    } else result = deterministicClassification(task, message);
    return parse(LibrarianArtifact, { schemaVersion: 'px.librarian-artifact/1.0', ...result, durationMs: performance.now() - started }, 'librarian-artifact');
  }
}

// Retain the old exported identifier for admitted callers and persisted contracts.
module.exports = { PXArchivist, TinyLibrarian: PXArchivist, deterministicClassification };
