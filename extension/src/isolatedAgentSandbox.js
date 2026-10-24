'use strict';

/**
 * Isolated Agent Sandbox mode — the single shared control surface.
 *
 * This module is the ONE owner of the sandbox mode value in the extension host.
 * Both UI surfaces (the top Chat Settings dropdown and the Side Panel Control
 * Panel) read and write through this owner, so they are never separate settings
 * and always stay synchronized.
 *
 * The UI only selects the mode. This module validates the selection, persists it
 * to the shared configuration value, and publishes a policy image. Neither this
 * module nor successful publication proves that containment is being enforced.
 */

function vscodeApi() { return require('vscode'); }

const SETTING_KEY = 'isolatedAgentSandbox';
const ALLOWED_ENDPOINTS_KEY = 'isolatedAgentSandbox.allowedEndpoints';
const MODES = Object.freeze(['OFF', 'ON']);
const CONFIG_SECTION = 'pacifyX';

// Bare host[:port] only: never a URL or path, so an authorized endpoint cannot
// smuggle a broad host match.
const ENDPOINT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?$/;

function normalizeMode(value) {
  if (typeof value !== 'string') return 'OFF';
  const upper = value.trim().toUpperCase();
  return MODES.includes(upper) ? upper : 'OFF';
}

function normalizeEndpoints(values) {
  if (!Array.isArray(values)) return [];
  const seen = new Set();
  for (const raw of values) {
    if (typeof raw !== 'string') continue;
    const value = raw.trim();
    if (!value || !ENDPOINT_PATTERN.test(value)) continue;
    seen.add(value);
  }
  return [...seen].sort();
}

/** Read the single shared value from the workspace configuration. */
function readSandboxMode(resource) {
  const vscode = vscodeApi();
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION, resource ?? null);
  return normalizeMode(config.get(SETTING_KEY));
}

function readAllowedEndpoints(resource) {
  const vscode = vscodeApi();
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION, resource ?? null);
  return normalizeEndpoints(config.get(ALLOWED_ENDPOINTS_KEY));
}

/** The current sandbox mode as a comparable value for both UI surfaces. */
function currentSandboxSelection(resource) {
  return { mode: readSandboxMode(resource), allowedEndpoints: readAllowedEndpoints(resource) };
}

/**
 * Set the single shared value. Both callers (chat dropdown and control panel) go
 * through here, so the two surfaces can never diverge.
 */
async function setSandboxMode(mode, resource) {
  const vscode = vscodeApi();
  const normalized = normalizeMode(mode);
  const target = resource
    ? vscode.ConfigurationTarget.WorkspaceFolder
    : vscode.ConfigurationTarget.Workspace;
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION, resource ?? null);
  await config.update(SETTING_KEY, normalized, target);
  return normalized;
}

async function setAllowedEndpoints(endpoints, resource) {
  const vscode = vscodeApi();
  const normalized = normalizeEndpoints(endpoints);
  const target = resource
    ? vscode.ConfigurationTarget.WorkspaceFolder
    : vscode.ConfigurationTarget.Workspace;
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION, resource ?? null);
  await config.update(ALLOWED_ENDPOINTS_KEY, normalized, target);
  return normalized;
}

/**
 * Build the runtime sandbox policy image. The UI declares the selected mode and
 * allowlist; runtime validation/persistence does not prove platform enforcement.
 */
function buildSandboxPolicyRequest(resource) {
  const selection = currentSandboxSelection(resource);
  return {
    schema_version: 'px.isolated-agent-sandbox-request/1.0',
    mode: selection.mode,
    allowed_endpoints: selection.mode === 'ON' ? selection.allowedEndpoints : [],
  };
}

module.exports = {
  SETTING_KEY,
  ALLOWED_ENDPOINTS_KEY,
  CONFIG_SECTION,
  MODES,
  normalizeMode,
  normalizeEndpoints,
  readSandboxMode,
  readAllowedEndpoints,
  currentSandboxSelection,
  setSandboxMode,
  setAllowedEndpoints,
  buildSandboxPolicyRequest
};