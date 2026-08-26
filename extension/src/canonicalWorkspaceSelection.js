'use strict';

const path = require('path');
const fs = require('fs');

function resolveCanonicalWorkspaceRoot({ configuredValue, explicitlyConfigured, projectRoot, exists = fs.existsSync } = {}) {
  const configured = String(configuredValue || '').trim();
  if (configured) return path.resolve(configured);
  if (explicitlyConfigured) return '';
  const candidate = String(projectRoot || '').trim();
  if (!candidate) return '';
  const resolved = path.resolve(candidate);
  return exists(path.join(resolved, 'engineering-workspace.toml')) ? resolved : '';
}

module.exports = { resolveCanonicalWorkspaceRoot };
