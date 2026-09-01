'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { canonicalJson, keyId, signClaim } = require('./studioApprovalHost');

const AUTHORITY_SCHEMA = 'px.mcp-launch-authority/1.0';
const MAX_LIFETIME_MS = 24 * 60 * 60 * 1000;
const MUTATING_TOOL_NAMES = Object.freeze([
  'pacify_enterprise_readiness',
  'pacify_enterprise_pack_set',
  'pacify_enterprise_target_configure',
  'pacify_activity_emit',
  'pacify_parallel_plan_create',
  'pacify_task_claim',
  'pacify_claim_renew',
  'pacify_task_progress',
  'pacify_task_reconcile',
  'pacify_task_release',
  'pacify_memory_capture',
  'pacify_team_pack_stage'
]);

function sha(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function physicalProjectIdentity(projectRoot) {
  if (!projectRoot) throw new Error('MCP project authority root is unavailable.');
  const resolved = fs.realpathSync.native(path.resolve(projectRoot));
  const stat = fs.statSync(resolved);
  if (!stat.isDirectory()) throw new Error('MCP project authority root is not a directory.');
  return sha(process.platform === 'win32' ? resolved.toLowerCase() : resolved);
}

function encodeClaim(claim) {
  return Buffer.from(canonicalJson(claim), 'utf8').toString('base64url');
}

function decodeClaim(value) {
  const raw = Buffer.from(String(value || ''), 'base64url');
  if (!raw.length || raw.length > 16 * 1024) throw new Error('MCP authority claim is invalid.');
  const claim = JSON.parse(raw.toString('utf8'));
  if (!claim || Array.isArray(claim) || typeof claim !== 'object') throw new Error('MCP authority claim is invalid.');
  return claim;
}

function createLaunchAuthority({ projectRoot, sessionId, keyMaterial, now = Date.now, lifetimeMs = 12 * 60 * 60 * 1000 }) {
  const issuedMs = Number(now());
  const boundedLifetime = Math.min(Math.max(Number(lifetimeMs) || 0, 60_000), MAX_LIFETIME_MS);
  const token = crypto.randomBytes(32).toString('base64url');
  const claim = {
    schema_version: AUTHORITY_SCHEMA,
    key_id: keyMaterial.keyId,
    project_sha256: physicalProjectIdentity(projectRoot),
    session_id: String(sessionId || ''),
    actor_id: 'vscode-mcp-host',
    harness: 'VS Code MCP',
    accountable_owner: 'local-user',
    allowed_operations: [...MUTATING_TOOL_NAMES],
    token_sha256: sha(token),
    issued_at: new Date(issuedMs).toISOString(),
    expires_at: new Date(issuedMs + boundedLifetime).toISOString()
  };
  if (!claim.session_id) throw new Error('MCP host session identity is unavailable.');
  return { claim: encodeClaim(claim), signature: signClaim(keyMaterial, claim), token };
}

function verifiedLaunchAuthority({ projectRoot, claim: encodedClaim, signature, token, publicKeyJwk, trustedKeyId, now = Date.now }) {
  const claim = decodeClaim(encodedClaim);
  const issuedMs = Date.parse(claim.issued_at);
  const expiresMs = Date.parse(claim.expires_at);
  const allowed = Array.isArray(claim.allowed_operations) ? claim.allowed_operations : [];
  const structurallyValid = claim.schema_version === AUTHORITY_SCHEMA &&
    /^[0-9a-f]{64}$/.test(String(claim.key_id || '')) && claim.key_id === trustedKeyId &&
    publicKeyJwk?.kty === 'RSA' && keyId(publicKeyJwk) === trustedKeyId &&
    claim.project_sha256 === physicalProjectIdentity(projectRoot) &&
    typeof claim.session_id === 'string' && claim.session_id.length > 0 && claim.session_id.length <= 200 &&
    claim.token_sha256 === sha(token) &&
    Number.isFinite(issuedMs) && Number.isFinite(expiresMs) && expiresMs > issuedMs &&
    expiresMs - issuedMs <= MAX_LIFETIME_MS && Number(now()) >= issuedMs - 30_000 && Number(now()) < expiresMs &&
    allowed.length === MUTATING_TOOL_NAMES.length &&
    MUTATING_TOOL_NAMES.every(name => allowed.includes(name));
  if (!structurallyValid) throw new Error('MCP host authority is unavailable or expired.');
  const verified = crypto.verify('sha256', Buffer.from(canonicalJson(claim), 'utf8'), {
    key: publicKeyJwk,
    format: 'jwk',
    padding: crypto.constants.RSA_PKCS1_PADDING
  }, Buffer.from(String(signature || ''), 'base64url'));
  if (!verified) throw new Error('MCP host authority signature is invalid.');
  return claim;
}

function deniedResult() {
  const value = { available: false, authorized: false, reason: 'A current authenticated Pacify-X host capability is required for this write.' };
  return { isError: true, content: [{ type: 'text', text: JSON.stringify(value) }], structuredContent: value };
}

function createMcpMutationAuthority(options) {
  let claim;
  let failure;
  try { claim = verifiedLaunchAuthority(options); } catch (error) { failure = error; }
  return {
    authorize(operation, input = {}) {
      if (failure || Number(options.now?.() ?? Date.now()) >= Date.parse(claim?.expires_at) ||
        !claim?.allowed_operations.includes(operation)) return { authorized: false, result: deniedResult() };
      const sanitizedInput = {
        ...input,
        actor_id: claim.actor_id,
        session_id: claim.session_id,
        harness: claim.harness,
        accountable_owner: claim.accountable_owner
      };
      return {
        authorized: true,
        input: sanitizedInput,
        attestation: {
          actor: {
            actorId: claim.actor_id,
            sessionId: claim.session_id,
            harness: claim.harness,
            accountableOwner: claim.accountable_owner
          },
          actorKind: 'host',
          identityAttestation: 'authenticated_host_capability',
          unattestedFields: []
        }
      };
    }
  };
}

module.exports = {
  AUTHORITY_SCHEMA, MUTATING_TOOL_NAMES, createLaunchAuthority, createMcpMutationAuthority,
  physicalProjectIdentity, verifiedLaunchAuthority
};
