'use strict';

const { performance } = require('node:perf_hooks');
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

class TinyLibrarian {
  constructor(options = {}) { this.modelRunner = options.modelRunner || null; }

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

module.exports = { TinyLibrarian, deterministicClassification };
