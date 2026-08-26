'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const controller = fs.readFileSync(
  path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'),
  'utf8'
);

test('Agent Studio exposes only the current editable graph control path', () => {
  assert.match(controller, /function upgradeAgentTopology\(root\)/);
  assert.match(controller, /upgradeAgentTopology\(document\.querySelector\('\.studio-editor-root'\)\)/);
  assert.match(controller, /data-action="agentSelectNode"/);
  assert.doesNotMatch(controller, /data-action="agentSelectSection"/);
  assert.doesNotMatch(controller, /action === 'agentSelectSection'/);
});
