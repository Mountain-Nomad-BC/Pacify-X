'use strict';

// Pacify-X credential-handling guard.
//
// Owner decision 2026-09-23 (policies/release-invariants.json -> owner_decisions
// [Q8-workspace-credential-migration]):
//
//   SecretStorage is the ONLY operational credential source. A workspace / .vscode value is a
//   migration source, never a fallback. Migration is explicit and user-initiated, never automatic.
//
// This guard fails the check if the code violates any of those rules, so the decision cannot be
// quietly reversed by a later change.

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const SRC = path.join(root, 'src');

const SECRET_API = /\bsecrets\.(?:get|store|delete)\b|\bSecretStorage\b/;

// Reading a credential out of a workspace/config file and using it.
const WORKSPACE_CREDENTIAL_READ = [
  /workspace\.getConfiguration\([^)]*\)\s*\.get\(\s*['"][^'"]*(?:api.?key|token|secret|password)/i,
  /settings\(\s*\)\s*\.\s*(?:apiKey|openaiApiKey|token|secret)\b/,
  /\.vscode[\\/][^'"`]*\.json[^'"`]*['"`][\s\S]{0,200}?(?:api.?key|token|secret)/i,
];

// Storing a credential value outside SecretStorage.
const SECRET_STORED_OUTSIDE_SECRETS = [
  /workspaceState\.update\(\s*['"][^'"]*(?:api.?key|token|secret|password)/i,
  /globalState\.update\(\s*['"][^'"]*(?:api.?key|token|secret|password)/i,
];

// Logging a credential.
const SECRET_LOGGED = [
  /appendLine\([^)]*\b(?:apiKey|api_key|token|secret|password|credential)\b/i,
  /console\.(?:log|error|warn)\([^)]*\b(?:apiKey|api_key|token|secret|password|credential)\b/i,
];

function walk(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.isFile() && entry.name.endsWith('.js') && entry.name !== 'extension.bundle.js') out.push(full);
  }
  return out;
}

const files = walk(SRC);
const findings = [];
let secretsApiUsers = 0;

for (const file of files) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { continue; }
  const relative = path.relative(root, file);
  if (SECRET_API.test(text)) secretsApiUsers += 1;

  text.split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
    const where = `${relative}:${index + 1}`;

    if (WORKSPACE_CREDENTIAL_READ.some(pattern => pattern.test(line))) {
      findings.push({ rule: 'workspace-credential-read', where, text: trimmed.slice(0, 130) });
    }
    if (SECRET_STORED_OUTSIDE_SECRETS.some(pattern => pattern.test(line))) {
      findings.push({ rule: 'secret-stored-outside-secretstorage', where, text: trimmed.slice(0, 130) });
    }
    if (SECRET_LOGGED.some(pattern => pattern.test(line))) {
      findings.push({ rule: 'secret-logged', where, text: trimmed.slice(0, 130) });
    }
  });
}

// The migration path, when it exists, must be user-initiated and must not be a fallback.
const migrationMarkers = [];
for (const file of files) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { continue; }
  const relative = path.relative(root, file);
  if (/migrat/i.test(text) && SECRET_API.test(text)) {
    migrationMarkers.push(relative);
    if (!/showInformationMessage|showWarningMessage|showQuickPick|showInputBox/.test(text)) {
      findings.push({
        rule: 'migration-not-user-initiated',
        where: relative,
        text: 'a migration path exists but no user-facing prompt was found',
      });
    }
  }
}

if (findings.length === 0) {
  console.log(
    `credential handling guard PASS (secretStorage users: ${secretsApiUsers}; ` +
    `migration paths: ${migrationMarkers.length || 'none'}; no workspace-credential reads, ` +
    `no secrets outside SecretStorage, no secrets logged)`
  );
  process.exit(0);
}

for (const finding of findings) {
  console.error(`FAIL [${finding.rule}] ${finding.where}  ${finding.text}`);
}
console.error('See docs/security/CREDENTIAL_HANDLING.md and policies/release-invariants.json (owner_decisions[Q8]).');
process.exit(1);