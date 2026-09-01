'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ownedNativeInputConfig, requestOwnedNativeInput, retryableActivationRefusal, validateResult } = require('../scripts/owned-native-input-client');

function fixture(t) {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-native-input-client-'));
  t.after(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));
  const root = path.join(temporaryRoot, 'native-input');
  const token = path.join(temporaryRoot, 'user-data');
  fs.mkdirSync(path.join(root, 'requests'), { recursive: true });
  fs.mkdirSync(path.join(root, 'results'), { recursive: true });
  fs.mkdirSync(token);
  const env = {
    PX_OWNED_NATIVE_INPUT_ROOT: root,
    PX_OWNED_NATIVE_INPUT_TOKEN: token,
    PX_OWNED_NATIVE_INPUT_SECRET: 'a'.repeat(64),
    PX_OWNED_NATIVE_INPUT_VSCODE_PID: '4242'
  };
  return { root, token, env, config: ownedNativeInputConfig(env, 'win32') };
}

test('owned native input configuration requires the exact sibling owned boundary', t => {
  const value = fixture(t);
  assert.equal(value.config.root, value.root);
  assert.equal(value.config.vscodePid, 4242);
  assert.throws(() => ownedNativeInputConfig({ ...value.env, PX_OWNED_NATIVE_INPUT_ROOT: path.join(os.tmpdir(), 'outside') }, 'win32'), /root-boundary-invalid/);
  assert.throws(() => ownedNativeInputConfig(value.env, 'linux'), /platform-unsupported/);
  assert.throws(() => ownedNativeInputConfig({ ...value.env, PX_OWNED_NATIVE_INPUT_SECRET: 'short' }, 'win32'), /secret-invalid/);
});

test('owned native input client publishes one authenticated request and accepts exact proof', async t => {
  const value = fixture(t);
  let serviced = false;
  const proof = await requestOwnedNativeInput('Build graph', { type: 'buildRepositoryGraph', requestId: 'host-request-7' }, {
    config: value.config,
    timeoutMs: 1_000,
    wait: async () => {
      if (serviced) return;
      const requestFile = fs.readdirSync(path.join(value.root, 'requests')).find(name => name.endsWith('.json'));
      if (!requestFile) return;
      serviced = true;
      const request = JSON.parse(fs.readFileSync(path.join(value.root, 'requests', requestFile), 'utf8'));
      fs.writeFileSync(path.join(value.root, 'results', requestFile), `${JSON.stringify({
        schema_version: 'px.owned-native-input-result/1.0', request_id: request.request_id, sequence: request.sequence,
        status: 'sent', foreground_pid: 4300, foreground_hwnd: '991', owned_process: true, input_count: 2, focus_recovered: true,
        observed_utc: new Date().toISOString()
      })}\n`);
    }
  });
  assert.equal(proof.action, 'approve');
  assert.equal(proof.key, 'enter');
  assert.equal(proof.foreground_pid, 4300);
  assert.equal(proof.focus_recovered, true);
  const request = JSON.parse(fs.readFileSync(path.join(value.root, 'requests', fs.readdirSync(path.join(value.root, 'requests'))[0]), 'utf8'));
  assert.equal(request.secret, 'a'.repeat(64));
  assert.deepEqual(request.correlation, { request_type: 'buildRepositoryGraph', request_id: 'host-request-7', action_label: 'Build graph' });
});

test('owned native input proof fails closed on refusal, mismatch, or incomplete SendInput', () => {
  const request = { request_id: 'request', sequence: 4, action: 'approve', key: 'enter' };
  assert.throws(() => validateResult({ schema_version: 'px.owned-native-input-result/1.0', request_id: 'request', sequence: 4, status: 'refused', reason: 'foreground mismatch' }, request), /refused:foreground mismatch/);
  assert.throws(() => validateResult({ schema_version: 'px.owned-native-input-result/1.0', request_id: 'other', sequence: 4, status: 'sent' }, request), /result-invalid/);
  assert.throws(() => validateResult({ schema_version: 'px.owned-native-input-result/1.0', request_id: 'request', sequence: 4, status: 'sent', foreground_pid: 1, owned_process: true, input_count: 1 }, request), /proof-invalid/);
  assert.throws(() => validateResult({ schema_version: 'px.owned-native-input-result/1.0', request_id: 'request', sequence: 4, status: 'sent', foreground_pid: 1, owned_process: true, input_count: 2 }, request), /proof-invalid/);
});

test('owned native input retries only a bounded owned-window activation refusal', async t => {
  const value = fixture(t);
  const serviced = new Set();
  const proof = await requestOwnedNativeInput('Stage candidates', { type: 'teamPackPreview', requestId: 'host-request-retry' }, {
    config: value.config,
    timeoutMs: 1_000,
    wait: async () => {
      const requestFile = fs.readdirSync(path.join(value.root, 'requests'))
        .filter(name => name.endsWith('.json') && !serviced.has(name)).sort()[0];
      if (!requestFile) return;
      serviced.add(requestFile);
      const request = JSON.parse(fs.readFileSync(path.join(value.root, 'requests', requestFile), 'utf8'));
      const refused = serviced.size === 1;
      fs.writeFileSync(path.join(value.root, 'results', requestFile), `${JSON.stringify(refused ? {
        schema_version: 'px.owned-native-input-result/1.0', request_id: request.request_id, sequence: request.sequence,
        status: 'refused', reason: 'PermissionError:owned VS Code window activation was refused'
      } : {
        schema_version: 'px.owned-native-input-result/1.0', request_id: request.request_id, sequence: request.sequence,
        status: 'sent', foreground_pid: 4300, foreground_hwnd: '992', owned_process: true, input_count: 2,
        focus_recovered: true, observed_utc: new Date().toISOString()
      })}\n`);
    }
  });
  assert.equal(serviced.size, 2);
  assert.equal(proof.status, 'sent');
  assert.equal(retryableActivationRefusal(new Error('owned-native-input-refused:PermissionError:owned VS Code window activation was refused')), true);
  assert.equal(retryableActivationRefusal(new Error('owned-native-input-refused:foreground mismatch')), false);
});
