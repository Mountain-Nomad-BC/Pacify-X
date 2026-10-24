'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('module');
const sandboxModule = require('../src/isolatedAgentSandbox');

test('sandbox module imports under plain Node without VS Code being loaded', () => {
  assert.equal(typeof sandboxModule.buildSandboxPolicyRequest, 'function');
});

function withSandbox(settings, callback) {
  const originalLoad = Module._load;
  const vscode = {
    ConfigurationTarget: { Workspace: 1, WorkspaceFolder: 2 },
    workspace: {
      getConfiguration: () => ({
        get: key => settings[key],
        update: async (key, value) => { settings[key] = value; }
      })
    }
  };
  Module._load = function(request, parent, isMain) {
    return request === 'vscode' ? vscode : originalLoad.call(this, request, parent, isMain);
  };
  try {
    const modulePath = require.resolve('../src/isolatedAgentSandbox');
    delete require.cache[modulePath];
    return callback(require(modulePath));
  } finally {
    Module._load = originalLoad;
  }
}

test('sandbox OFF publishes an empty runtime allowlist while preserving UI settings', () => {
  const settings = {
    isolatedAgentSandbox: 'OFF',
    'isolatedAgentSandbox.allowedEndpoints': ['api.example.com']
  };
  withSandbox(settings, sandbox => {
    assert.deepEqual(sandbox.buildSandboxPolicyRequest(), {
      schema_version: 'px.isolated-agent-sandbox-request/1.0',
      mode: 'OFF',
      allowed_endpoints: []
    });
  });
  assert.deepEqual(settings['isolatedAgentSandbox.allowedEndpoints'], ['api.example.com']);
});

test('sandbox ON publishes its configured allowlist', () => {
  const settings = {
    isolatedAgentSandbox: 'ON',
    'isolatedAgentSandbox.allowedEndpoints': ['api.example.com']
  };
  withSandbox(settings, sandbox => {
    assert.deepEqual(sandbox.buildSandboxPolicyRequest().allowed_endpoints, ['api.example.com']);
  });
});
