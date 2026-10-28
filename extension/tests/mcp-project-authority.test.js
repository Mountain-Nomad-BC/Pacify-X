'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { once } = require('node:events');
const { generateApprovalKey } = require('../src/studioApprovalHost');
const { createLaunchAuthority } = require('../src/mcpMutationAuthority');

for (const replacement of ['directory', 'junction']) {
  test(`bundled MCP denies a write after its project root becomes another ${replacement}`, { timeout: 20000 }, async t => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'px-mcp-root-binding-'));
    t.after(() => fs.rmSync(scratch, { recursive: true, force: true }));
    const workspace = path.join(scratch, 'project');
    const retained = path.join(scratch, 'original-project');
    const foreign = path.join(scratch, 'foreign-project');
    fs.mkdirSync(workspace); fs.mkdirSync(foreign);
    const keyMaterial = generateApprovalKey();
    const authority = createLaunchAuthority({ projectRoot: workspace, sessionId: 'root-bound-host', keyMaterial });
    const publicJwkPath = path.join(scratch, 'public-jwk.json');
    fs.writeFileSync(publicJwkPath, JSON.stringify(keyMaterial.publicKeyJwk));
    const extensionRoot = path.resolve(__dirname, '..');
    const child = cp.spawn(process.execPath, [path.join(extensionRoot, 'server', 'index.js')], {
      cwd: extensionRoot, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env, PX_CONTEXT_PATH: path.join(extensionRoot, 'tests', 'fixtures', 'context.json'),
        PX_WORKSPACE_ROOT: workspace, PX_COORDINATION_ROOT: workspace,
        PX_MCP_AUTHORITY_CLAIM: authority.claim, PX_MCP_AUTHORITY_SIGNATURE: authority.signature,
        PX_MCP_AUTHORITY_TOKEN: authority.token, PX_MCP_AUTHORITY_PUBLIC_JWK_PATH: publicJwkPath,
        PX_MCP_AUTHORITY_KEY_ID: keyMaterial.keyId
      }
    });
    const lines = readline.createInterface({ input: child.stdout });
    const messages = []; let stderr = '';
    lines.on('line', line => { if (line.trim()) messages.push(JSON.parse(line)); });
    child.stderr.setEncoding('utf8'); child.stderr.on('data', data => { stderr += data; });
    const send = value => child.stdin.write(`${JSON.stringify(value)}\n`);
    async function response(id) {
      for (let attempt = 0; attempt < 160; attempt += 1) {
        const found = messages.find(message => message.id === id); if (found) return found;
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      throw new Error(`MCP response ${id} timed out: ${stderr}`);
    }
    try {
      send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'root-binding-test', version: '1.0.0' } } });
      await response(1);
      send({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
      fs.renameSync(workspace, retained);
      if (replacement === 'junction') fs.symlinkSync(foreign, workspace, process.platform === 'win32' ? 'junction' : 'dir');
      else fs.mkdirSync(workspace);
      send({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'pacify_parallel_plan_create', arguments: {
        actor_id: 'forged-owner', session_id: 'forged-session', harness: 'untrusted-client',
        objective: 'must not mutate replacement project', tasks: [{ id: 'denied', title: 'Denied', claims: ['docs/'] }]
      } } });
      const denied = await response(2);
      assert.equal(denied.result.isError, true, JSON.stringify(denied));
      assert.equal(denied.result.structuredContent.authorized, false);
      assert.deepEqual(fs.readdirSync(workspace), []);
      assert.deepEqual(fs.readdirSync(foreign), []);
      assert.deepEqual(fs.readdirSync(retained), []);
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        const exited = once(child, 'exit');
        child.kill(); await exited;
      }
      lines.close();
    }
  });
}
