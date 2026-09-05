'use strict';

const fs = require('fs');
const path = require('path');
const {
  CONFORMANCE_VIOLATION_IDS,
  coordinationConformanceReport
} = require('../src/stateInvariants');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function mutate(state, mutation) {
  let target = state;
  const parts = mutation.path;
  for (const part of parts.slice(0, -1)) target = target[part];
  const leaf = parts.at(-1);
  if (mutation.op === 'set') target[leaf] = clone(mutation.value);
  else if (mutation.op === 'append') target[leaf].push(clone(mutation.value));
  else throw new Error(`unsupported conformance mutation: ${mutation.op}`);
}

function runVectors(corpus) {
  if (corpus.schema_version !== 'px.coordination-state-conformance-vectors/1.0') {
    throw new Error('coordination conformance vector schema is invalid');
  }
  if (JSON.stringify(corpus.evaluation_order) !== JSON.stringify(CONFORMANCE_VIOLATION_IDS)) {
    throw new Error('coordination conformance evaluation order drifted');
  }
  return corpus.vectors.map(vector => {
    const state = clone(corpus.base_state);
    for (const mutation of vector.mutations) mutate(state, mutation);
    return {
      id: vector.id,
      ...coordinationConformanceReport(state, { nowUtc: corpus.now_utc })
    };
  });
}

if (require.main === module) {
  const corpusPath = process.argv[2];
  if (!corpusPath) throw new Error('vector corpus path is required');
  const corpus = JSON.parse(fs.readFileSync(path.resolve(corpusPath), 'utf8'));
  process.stdout.write(`${JSON.stringify({ results: runVectors(corpus) })}\n`);
}

module.exports = { runVectors };
