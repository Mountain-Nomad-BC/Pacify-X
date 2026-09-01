'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { generateApprovalKey } = require('../src/studioApprovalHost');
const { createLaunchAuthority, createMcpMutationAuthority, verifiedLaunchAuthority } = require('../src/mcpMutationAuthority');

function fixture(t) {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-mcp-authority-'));
  t.after(() => fs.rmSync(projectRoot, { recursive: true, force: true }));
  const keyMaterial = generateApprovalKey();
  const launched = createLaunchAuthority({ projectRoot, sessionId: 'host-session', keyMaterial, now: () => 1_800_000_000_000 });
  return { projectRoot, keyMaterial, launched };
}

test('signed launch authority replaces self-asserted MCP identity', t => {
  const { projectRoot, keyMaterial, launched } = fixture(t);
  const authority = createMcpMutationAuthority({
    projectRoot, claim: launched.claim, signature: launched.signature, token: launched.token,
    publicKeyJwk: keyMaterial.publicKeyJwk, trustedKeyId: keyMaterial.keyId,
    now: () => 1_800_000_001_000
  });
  const decision = authority.authorize('pacify_task_claim', {
    actor_id: 'impersonated-owner', session_id: 'forged-session', harness: 'forged-client', task_id: 'one'
  });
  assert.equal(decision.authorized, true);
  assert.deepEqual(
    [decision.input.actor_id, decision.input.session_id, decision.input.harness],
    ['vscode-mcp-host', 'host-session', 'VS Code MCP']
  );
  assert.equal(decision.attestation.identityAttestation, 'authenticated_host_capability');
});

test('launch authority fails closed for replay in another project, changed token, and unadmitted operation', t => {
  const { projectRoot, keyMaterial, launched } = fixture(t);
  const otherRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-mcp-other-'));
  t.after(() => fs.rmSync(otherRoot, { recursive: true, force: true }));
  assert.throws(() => verifiedLaunchAuthority({
    projectRoot: otherRoot, claim: launched.claim, signature: launched.signature, token: launched.token,
    publicKeyJwk: keyMaterial.publicKeyJwk, trustedKeyId: keyMaterial.keyId, now: () => 1_800_000_001_000
  }));
  assert.throws(() => verifiedLaunchAuthority({
    projectRoot, claim: launched.claim, signature: launched.signature, token: 'changed-token',
    publicKeyJwk: keyMaterial.publicKeyJwk, trustedKeyId: keyMaterial.keyId, now: () => 1_800_000_001_000
  }));
  const authority = createMcpMutationAuthority({
    projectRoot, claim: launched.claim, signature: launched.signature, token: launched.token,
    publicKeyJwk: keyMaterial.publicKeyJwk, trustedKeyId: keyMaterial.keyId, now: () => 1_800_000_001_000
  });
  assert.equal(authority.authorize('pacify_unadmitted_write', {}).authorized, false);
});
