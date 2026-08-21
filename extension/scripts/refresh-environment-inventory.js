'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { discoverEnvironment } = require('../src/discoveryManager');

function packageDirectories() {
  const roots = [path.join(os.homedir(), '.vscode', 'extensions')];
  const codePath = process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, 'Programs', 'Microsoft VS Code', 'resources', 'app', 'extensions')
    : null;
  if (codePath) roots.push(codePath);
  return roots;
}

function extensionMetadata(roots) {
  const records = [];
  const seen = new Set();
  for (const root of roots) {
    let entries;
    try { entries = fs.readdirSync(root, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
      const manifestPath = path.join(root, entry.name, 'package.json');
      let manifest;
      try {
        const stat = fs.statSync(manifestPath);
        if (!stat.isFile() || stat.size > 2 * 1024 * 1024) continue;
        manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
      } catch { continue; }
      const id = `${manifest.publisher || 'vscode'}.${manifest.name || entry.name}`;
      if (seen.has(id)) continue;
      seen.add(id);
      records.push({ id, packageJSON: manifest, isActive: false });
    }
  }
  return records.sort((left, right) => left.id.localeCompare(right.id));
}

async function main() {
  if (process.argv.includes('--help')) {
    process.stdout.write('Usage: node scripts/refresh-environment-inventory.js --root <repository-root>\n');
    return;
  }
  const index = process.argv.indexOf('--root');
  if (index < 0 || !process.argv[index + 1]) throw new Error('--root is required');
  const root = path.resolve(process.argv[index + 1]);
  if (root === path.parse(root).root || !fs.statSync(root).isDirectory()) throw new Error('repository root is invalid');
  const extensions = extensionMetadata(packageDirectories());
  const result = await discoverEnvironment({
    extensions,
    projectRoot: root,
    engineRoot: root,
    pythonPath: process.platform === 'win32' ? 'python.exe' : 'python3',
    reason: 'governed-canonical-environment-refresh',
    persist: true,
  });
  process.stdout.write(`${JSON.stringify({
    schema_version: result.inventory.schema_version,
    generated_utc: result.inventory.generated_utc,
    snapshot_hash: result.inventory.snapshot_hash,
    extension_count: result.inventory.summary.extensions,
    tool_count: result.inventory.summary.system_tools,
    python_package_count: result.inventory.summary.python_packages,
    generation: result.inventory.discovery.generation,
    credential_values_persisted: result.inventory.boundaries.credential_values_persisted,
  }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
