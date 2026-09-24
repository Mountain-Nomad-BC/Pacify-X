'use strict';

// Pacify-X extension telemetry guard (release invariant: no-production-remote-telemetry).
//
// Owner decision 2026-09-23: the 0.9.x core emits NO production telemetry. Do not add
// telemetry merely to satisfy a compliance requirement. This guard exists so the invariant is
// machine-verifiable and cannot be violated by accident:
//
//   * if NO telemetry emitter exists            -> PASS (current state)
//   * if an emitter exists AND is gated by
//     VS Code's isTelemetryEnabled/telemetryLevel
//     AND a telemetry manifest + documentation     -> PASS (a deliberate future change)
//   * if an emitter exists WITHOUT that gating     -> FAIL
//
// Local operational logs, traces, certification evidence and diagnostics that stay on the
// user's machine are NOT remote telemetry and are not flagged.

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const PRODUCTION_AREAS = ['src', 'media'];
const SKIP_FILES = ['extension.bundle.js'];

// A genuine emitter is a call/construction, not a vocabulary entry in a keyword table.
const EMITTER_PATTERNS = [
  /\bsendTelemetryEvent\s*\(/,
  /\bTelemetryReporter\b/,
  /\bnew\s+TelemetryReporter\b/,
  /\b(?:appInsights|applicationinsights)\s*[.(]/i,
  /\bsentry\.(?:capture|init)\s*\(/i,
  /\bposthog\.(?:capture|init)\s*\(/i,
  /\bmixpanel\.(?:track|init)\s*\(/i,
  /\bsegment\.(?:track|analytics)\s*\(/i,
  /\bopentelemetry\b[^"'`]*\.(?:start|record|add)\s*\(/i,
];

const GUARD_PATTERNS = [
  /\bisTelemetryEnabled\b/,
  /\bonDidChangeTelemetryEnabled\b/,
  /\btelemetryLevel\b/,
  /\benv\.isTelemetryEnabled\b/,
];

function walk(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.isFile() && entry.name.endsWith('.js') && !SKIP_FILES.includes(entry.name)) out.push(full);
  }
  return out;
}

const files = PRODUCTION_AREAS.flatMap(area => walk(path.join(root, area)));
const emitters = [];
const guards = [];

for (const file of files) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { continue; }
  const relative = path.relative(root, file);
  text.split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
    if (EMITTER_PATTERNS.some(pattern => pattern.test(line))) {
      emitters.push({ file: relative, line: index + 1, text: trimmed.slice(0, 120) });
    }
    if (GUARD_PATTERNS.some(pattern => pattern.test(line))) {
      guards.push(`${relative}:${index + 1}`);
    }
  });
}

const manifestPath = path.join(root, 'telemetry.json');
const hasManifest = fs.existsSync(manifestPath);

if (emitters.length === 0) {
  console.log('extension telemetry guard PASS (no production remote telemetry emitters found)');
  process.exit(0);
}

// An emitter exists: it is only acceptable with the VS Code opt-out contract and disclosure.
const problems = [];
if (guards.length === 0) {
  problems.push('a production telemetry emitter exists but no isTelemetryEnabled/telemetryLevel guard was found');
}
if (!hasManifest) {
  problems.push('a production telemetry emitter exists but extension/telemetry.json is missing');
}
if (problems.length) {
  for (const emitter of emitters) {
    console.error(`emitter: ${emitter.file}:${emitter.line}  ${emitter.text}`);
  }
  for (const problem of problems) console.error(`FAIL: ${problem}`);
  console.error('See TELEMETRY.md and policies/release-invariants.json (no-production-remote-telemetry).');
  process.exit(1);
}

console.log(`extension telemetry guard PASS (${emitters.length} gated emitter(s), manifest present, guards at ${guards.join(', ')})`);