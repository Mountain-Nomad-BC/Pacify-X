'use strict';

const crypto = require('crypto');

const KEYRING_SECRET = 'pacifyX.studioApprovalSigningKeyring.v2';

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

function approvalPayloadJson(value) {
  const serialized = JSON.stringify(value);
  if (typeof serialized !== 'string' || serialized[0] !== '{') {
    throw new TypeError('Studio approval payload must be a JSON object.');
  }
  return serialized;
}

function keyId(publicKeyJwk) {
  return crypto.createHash('sha256').update(canonicalJson(publicKeyJwk), 'utf8').digest('hex');
}

function generateApprovalKey() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', {
    modulusLength: 3072,
    publicExponent: 0x10001
  });
  const publicKeyJwk = publicKey.export({ format: 'jwk' });
  return {
    keyId: keyId(publicKeyJwk),
    publicKeyJwk,
    privateKeyPem: privateKey.export({ format: 'pem', type: 'pkcs8' }).toString(),
    createdUtc: new Date().toISOString()
  };
}

function validMaterial(value) {
  return Boolean(value && /^[0-9a-f]{64}$/.test(String(value.keyId || '')) &&
    value.publicKeyJwk?.kty === 'RSA' && typeof value.privateKeyPem === 'string' &&
    keyId(value.publicKeyJwk) === value.keyId);
}

function createSecretStorageApprovalKeyProvider(secretStorage) {
  if (!secretStorage?.get || !secretStorage?.store) throw new TypeError('VS Code SecretStorage is required.');
  async function load() {
    const raw = await secretStorage.get(KEYRING_SECRET);
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed.schema_version === 'px.studio-approval-keyring/2.0' && validMaterial(parsed.active) &&
          Array.isArray(parsed.previous) && parsed.previous.every(validMaterial)) return parsed;
      } catch {}
    }
    const created = { schema_version: 'px.studio-approval-keyring/2.0', active: generateApprovalKey(), previous: [] };
    await secretStorage.store(KEYRING_SECRET, JSON.stringify(created));
    return created;
  }
  return async request => {
    const action = request?.action || 'get';
    let ring = await load();
    if (action === 'rotate') {
      ring = {
        schema_version: ring.schema_version,
        active: generateApprovalKey(),
        previous: [ring.active, ...ring.previous].slice(0, 2)
      };
      await secretStorage.store(KEYRING_SECRET, JSON.stringify(ring));
    }
    if (action === 'find') return [ring.active, ...ring.previous].find(item => item.keyId === request.keyId) || null;
    return ring;
  };
}

function signClaim(material, claim) {
  if (!validMaterial(material)) throw new Error('Studio approval signing key is invalid.');
  return crypto.sign('sha256', Buffer.from(canonicalJson(claim), 'utf8'), {
    key: material.privateKeyPem,
    padding: crypto.constants.RSA_PKCS1_PADDING
  }).toString('base64url');
}

module.exports = {
  KEYRING_SECRET, approvalPayloadJson, canonicalJson, keyId, generateApprovalKey,
  createSecretStorageApprovalKeyProvider, signClaim, validMaterial
};
