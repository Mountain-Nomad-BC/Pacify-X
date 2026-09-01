'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
let lastSequence = 0;

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function nextSequence(now = Date.now()) {
  const candidate = now * 1000;
  lastSequence = Math.max(lastSequence + 1, candidate);
  if (!Number.isSafeInteger(lastSequence)) throw new Error('owned-native-input-sequence-exhausted');
  return lastSequence;
}

function ownedNativeInputConfig(env = process.env, platform = process.platform) {
  if (platform !== 'win32') throw new Error('owned-native-input-platform-unsupported');
  const root = path.resolve(String(env.PX_OWNED_NATIVE_INPUT_ROOT || ''));
  const ownedToken = path.resolve(String(env.PX_OWNED_NATIVE_INPUT_TOKEN || ''));
  const secret = String(env.PX_OWNED_NATIVE_INPUT_SECRET || '');
  const vscodePid = Number(env.PX_OWNED_NATIVE_INPUT_VSCODE_PID);
  if (!root || !ownedToken || path.dirname(root) !== path.dirname(ownedToken) || !inside(path.dirname(ownedToken), root)) {
    throw new Error('owned-native-input-root-boundary-invalid');
  }
  if (!/^[a-f0-9]{64}$/.test(secret)) throw new Error('owned-native-input-secret-invalid');
  if (!Number.isSafeInteger(vscodePid) || vscodePid <= 0) throw new Error('owned-native-input-vscode-pid-invalid');
  if (!fs.existsSync(root) || fs.lstatSync(root).isSymbolicLink() || !fs.existsSync(ownedToken) || fs.lstatSync(ownedToken).isSymbolicLink()) {
    throw new Error('owned-native-input-root-boundary-invalid');
  }
  for (const leaf of ['requests', 'results']) {
    const directory = path.join(root, leaf);
    if (!fs.existsSync(directory) || !fs.lstatSync(directory).isDirectory() || fs.lstatSync(directory).isSymbolicLink()) {
      throw new Error(`owned-native-input-directory-invalid:${leaf}`);
    }
  }
  return Object.freeze({ root, ownedToken, secret, vscodePid });
}

function atomicJson(target, payload, fileSystem = fs) {
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fileSystem.writeFileSync(temporary, `${JSON.stringify(payload)}\n`, { encoding: 'utf8', flag: 'wx' });
  fileSystem.renameSync(temporary, target);
}

function validateResult(result, request) {
  if (result?.schema_version !== 'px.owned-native-input-result/1.0'
      || result.request_id !== request.request_id
      || result.sequence !== request.sequence
      || !['sent', 'refused'].includes(result.status)) {
    throw new Error('owned-native-input-result-invalid');
  }
  if (result.status !== 'sent') throw new Error(`owned-native-input-refused:${String(result.reason || 'unknown').slice(0, 160)}`);
  if (!Number.isSafeInteger(result.foreground_pid) || result.foreground_pid <= 0 || result.owned_process !== true || result.input_count !== 2 || typeof result.focus_recovered !== 'boolean') {
    throw new Error('owned-native-input-proof-invalid');
  }
  return Object.freeze({
    schema_version: result.schema_version,
    request_id: result.request_id,
    sequence: result.sequence,
    status: result.status,
    action: request.action,
    key: request.key,
    foreground_pid: result.foreground_pid,
    foreground_hwnd: String(result.foreground_hwnd || ''),
    owned_process: true,
    input_count: 2,
    focus_recovered: result.focus_recovered,
    observed_utc: String(result.observed_utc || '')
  });
}

function retryableActivationRefusal(error) {
  return /owned-native-input-refused:PermissionError:owned VS Code window activation was refused/i.test(String(error?.message || error));
}

async function requestOwnedNativeInput(label, outboundRequest, options = {}) {
  const config = options.config || ownedNativeInputConfig(options.env, options.platform);
  const requestType = String(outboundRequest?.type || '');
  if (!requestType) throw new Error('owned-native-input-correlation-missing');
  const action = label === 'Cancel' ? 'cancel' : 'approve';
  const key = action === 'cancel' ? 'escape' : 'enter';
  const maximumAttempts = Math.max(1, Math.min(2, Number(options.activationAttempts || 2)));
  let lastActivationRefusal = null;
  for (let attempt = 0; attempt < maximumAttempts; attempt += 1) {
    let retryRequested = false;
    const issued = Number(options.now?.() ?? Date.now());
    const sequence = nextSequence(issued);
    const request = {
      schema_version: 'px.owned-native-input-request/1.0',
      request_id: crypto.randomUUID(),
      sequence,
      secret: config.secret,
      vscode_pid: config.vscodePid,
      action,
      key,
      issued_utc: new Date(issued).toISOString(),
      expires_utc: new Date(issued + Number(options.ttlMs || 5_000)).toISOString(),
      correlation: {
        request_type: requestType.slice(0, 160),
        request_id: String(outboundRequest?.requestId || '').slice(0, 500),
        action_label: String(label).slice(0, 160)
      }
    };
    const requestPath = path.join(config.root, 'requests', `${sequence}.json`);
    const resultPath = path.join(config.root, 'results', `${sequence}.json`);
    atomicJson(requestPath, request, options.fileSystem || fs);
    const deadline = Date.now() + Number(options.timeoutMs || 7_000);
    while (Date.now() < deadline) {
      if (fs.existsSync(resultPath)) {
        const result = JSON.parse(fs.readFileSync(resultPath, 'utf8'));
        try {
          return validateResult(result, request);
        } catch (error) {
          if (!retryableActivationRefusal(error) || attempt + 1 >= maximumAttempts) throw error;
          lastActivationRefusal = error;
          retryRequested = true;
          break;
        }
      }
      await (options.wait || wait)(25);
    }
    if (!retryRequested) throw new Error(`owned-native-input-result-timeout:${sequence}`);
    await (options.wait || wait)(100);
  }
  throw lastActivationRefusal;
}

module.exports = { atomicJson, nextSequence, ownedNativeInputConfig, requestOwnedNativeInput, retryableActivationRefusal, validateResult };
