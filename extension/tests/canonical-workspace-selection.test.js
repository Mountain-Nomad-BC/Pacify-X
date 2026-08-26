'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { resolveCanonicalWorkspaceRoot } = require('../src/canonicalWorkspaceSelection');

test('uses an explicit canonical workspace root', () => {
  assert.equal(
    resolveCanonicalWorkspaceRoot({ configuredValue: 'C:/canonical', explicitlyConfigured: true, projectRoot: 'C:/project' }),
    path.resolve('C:/canonical')
  );
});

test('preserves explicit detach instead of automatically reattaching', () => {
  assert.equal(resolveCanonicalWorkspaceRoot({
    configuredValue: '', explicitlyConfigured: true, projectRoot: 'C:/project', exists: () => true
  }), '');
});

test('automatically selects an initialized open PX workspace when unset', () => {
  const projectRoot = path.resolve('C:/project');
  assert.equal(resolveCanonicalWorkspaceRoot({
    configuredValue: '', explicitlyConfigured: false, projectRoot,
    exists: candidate => candidate === path.join(projectRoot, 'engineering-workspace.toml')
  }), projectRoot);
});

test('does not infer an uninitialized project as a canonical workspace', () => {
  assert.equal(resolveCanonicalWorkspaceRoot({
    configuredValue: '', explicitlyConfigured: false, projectRoot: 'C:/project', exists: () => false
  }), '');
});
