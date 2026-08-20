'use strict';

const fs = require('fs');
const vscode = require('vscode');

const EXTENSION_ID = 'mountain-nomad-bc.pacify-x-vscode';
const COMMAND_ID = 'pacifyX.openDashboard';

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitForRelease(target, timeoutMs = 240_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (fs.existsSync(target)) return;
    await wait(100);
  }
  throw new Error('operational-walk-bootstrap-release-timeout');
}

function writeReceipt(target, receipt) {
  fs.writeFileSync(target, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
}

async function run() {
  const receiptPath = process.env.PX_OPERATIONAL_WALK_BOOTSTRAP_RECEIPT;
  const sentinelPath = process.env.PX_OPERATIONAL_WALK_BOOTSTRAP_SENTINEL;
  if (!receiptPath || !sentinelPath) throw new Error('operational-walk-bootstrap-paths-missing');
  const receipt = {
    schema_version: 'px.operational-walk-bootstrap/1.0',
    observed_utc: new Date().toISOString(),
    extension_id: EXTENSION_ID,
    command_id: COMMAND_ID,
    status: 'starting',
    extension_found: false,
    activation_completed: false,
    command_registered: false,
    command_executed: false
  };
  try {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    receipt.extension_found = Boolean(extension);
    if (!extension) throw new Error(`operational-extension-missing:${EXTENSION_ID}`);
    await extension.activate();
    receipt.activation_completed = true;
    const commands = await vscode.commands.getCommands(true);
    receipt.command_registered = commands.includes(COMMAND_ID);
    if (!receipt.command_registered) throw new Error(`operational-command-missing:${COMMAND_ID}`);
    await vscode.commands.executeCommand(COMMAND_ID);
    receipt.command_executed = true;
    receipt.status = 'ready';
    receipt.ready_utc = new Date().toISOString();
    writeReceipt(receiptPath, receipt);
    await waitForRelease(sentinelPath);
  } catch (error) {
    receipt.status = 'failed';
    receipt.error = String(error?.stack || error?.message || error).slice(0, 8000);
    receipt.failed_utc = new Date().toISOString();
    if (!fs.existsSync(receiptPath)) writeReceipt(receiptPath, receipt);
    throw error;
  }
}

module.exports = { run };
