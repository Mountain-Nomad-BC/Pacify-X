'use strict';

const cp = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

const extensionRoot = path.resolve(__dirname, '..');
const engineRoot = path.resolve(extensionRoot, '..');
const workspaceRoot = path.resolve(process.argv[2] || engineRoot);
const receiptPath = path.join(workspaceRoot, '.px', 'mcp-runtime-probe.json');
const token = `px-mcp-probe-${crypto.randomUUID()}`;
const receipt = {
  schema_version: 'px.mcp-runtime-probe/1.0', token, owner_pid: process.pid, child_pid: null,
  workspace_root: workspaceRoot.replaceAll('\\', '/'), started_utc: new Date().toISOString(),
  tool: 'pacify_context_snapshot', status: 'starting', child_exit_verified: false
};

function writeReceipt() {
  fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
  const temporary = `${receiptPath}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, receiptPath);
}

async function main() {
  const child = cp.spawn(process.execPath, [path.join(extensionRoot, 'server', 'index.js'), `--px-owned-token=${token}`], {
    cwd: extensionRoot, windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env, PX_CONTEXT_PATH: '', PX_ENGINE_ROOT: engineRoot,
      PX_WORKSPACE_ROOT: workspaceRoot, PX_COORDINATION_ROOT: workspaceRoot,
      PX_PYTHON_PATH: process.env.PX_PYTHON_PATH || 'python'
    }
  });
  receipt.child_pid = child.pid; receipt.status = 'running'; writeReceipt();
  const responses = []; let stderr = '';
  const lines = readline.createInterface({ input: child.stdout });
  lines.on('line', line => { if (line.trim()) responses.push(JSON.parse(line)); });
  child.stderr.setEncoding('utf8'); child.stderr.on('data', value => { stderr = `${stderr}${value}`.slice(-8000); });
  const send = value => child.stdin.write(`${JSON.stringify(value)}\n`);
  const waitFor = async id => {
    for (let attempt = 0; attempt < 200; attempt += 1) {
      const found = responses.find(value => value.id === id); if (found) return found;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw new Error(`mcp-runtime-probe-timeout:${id}:${stderr}`);
  };
  try {
    send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'pacify-runtime-probe', version: '1.0.0' } } });
    const initialized = await waitFor(1);
    if (initialized.error || initialized.result?.serverInfo?.name !== 'pacify-x-governed-context') throw new Error('mcp-runtime-initialize-invalid');
    send({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
    send({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: receipt.tool, arguments: {} } });
    const called = await waitFor(2);
    if (called.error || !called.result?.structuredContent) throw new Error('mcp-runtime-tool-call-invalid');
    receipt.server = initialized.result.serverInfo;
    receipt.tool_result_received = true;
    receipt.status = 'invoked';
  } finally {
    child.stdin.end();
    child.kill();
    await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('close', resolve); });
    receipt.child_exit_verified = true;
    receipt.finished_utc = new Date().toISOString();
    receipt.status = receipt.tool_result_received ? 'completed' : 'failed';
    writeReceipt();
  }
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
}

main().catch(error => {
  receipt.status = 'failed'; receipt.error = String(error?.message || error).slice(0, 2000);
  receipt.finished_utc = new Date().toISOString(); writeReceipt();
  process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1;
});
