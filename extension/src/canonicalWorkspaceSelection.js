'use strict';

const path = require('path');
const fs = require('fs');

function resolveCanonicalWorkspaceRoot({ configuredValue, explicitlyConfigured, configuredScope = 'workspace', projectRoot, exists = fs.existsSync } = {}) {
  const configured = String(configuredValue || '').trim();
  const projectScoped = configuredScope === 'workspace' || configuredScope === 'workspace-folder';
  if (configured && projectScoped) return path.resolve(configured);
  if (explicitlyConfigured && projectScoped) return '';
  const candidate = String(projectRoot || '').trim();
  if (!candidate) return '';
  const resolved = path.resolve(candidate);
  return exists(path.join(resolved, 'engineering-workspace.toml')) ? resolved : '';
}

module.exports = { resolveCanonicalWorkspaceRoot };
