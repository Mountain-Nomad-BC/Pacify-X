'use strict';

const crypto = require('node:crypto');

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;

function newId(prefix) {
  const safePrefix = SAFE_ID.test(prefix) ? prefix : 'px';
  return `${safePrefix}-${crypto.randomUUID()}`;
}

function requireSafeId(value, label = 'id') {
  const text = String(value || '');
  if (!SAFE_ID.test(text)) throw new Error(`${label}-invalid`);
  return text;
}

function nowIso() { return new Date().toISOString(); }
function sha256(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }

module.exports = { SAFE_ID, newId, requireSafeId, nowIso, sha256 };
