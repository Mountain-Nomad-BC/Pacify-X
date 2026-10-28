'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const path = require('node:path');
const extensionRoot = path.resolve(__dirname, '..');
for (const cwd of [path.dirname(extensionRoot), extensionRoot]) {
  test(`MCP bundled source check agrees when invoked from ${path.basename(cwd)}`, () => {
    const result = cp.spawnSync(process.execPath, [path.join(extensionRoot, 'scripts', 'build-mcp.js'), '--check'], {
      cwd, shell: false, windowsHide: true, encoding: 'utf8', timeout: 15000
    });
    assert.equal(result.status, 0, result.stderr || String(result.error || result.stdout));
  });
}
