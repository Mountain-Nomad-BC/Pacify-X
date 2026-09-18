'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { downloadAndUnzipVSCode } = require('@vscode/test-electron');
const { adoptOwnedVscodeTestCache, ensureOwnedVscodeTestCache, resolveOwnedCachedVSCode } = require('./owned-vscode-test-cache');

const DEFAULT_VERSION = '1.132.1';
const digest = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');

function argument(name, argv = process.argv.slice(2)) {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : null;
}

function cacheEvidence(cache, populated) {
  return {
    schema_version: 'px.owned-vscode-test-cache-preflight/1.0', valid: true,
    version: cache.version, platform: cache.platform, arch: cache.arch,
    root: cache.root, executable: cache.executable,
    executable_sha256: digest(cache.executable), populated,
    checked_utc: new Date().toISOString()
  };
}

async function prepareOwnedVscodeTestCache(version = DEFAULT_VERSION, options = {}) {
  const dependencies = options.dependencies || {
    resolve: resolveOwnedCachedVSCode,
    ensure: ensureOwnedVscodeTestCache,
    download: downloadAndUnzipVSCode
  };
  try {
    return cacheEvidence(dependencies.resolve(version, options), false);
  } catch (error) {
    if (options.checkOnly) throw error;
  }
  if (options.adoptExisting) {
    return cacheEvidence((dependencies.adopt || adoptOwnedVscodeTestCache)(version, options), false);
  }
  const owned = dependencies.ensure(version, options);
  await dependencies.download({ version, cachePath: owned.root });
  return cacheEvidence(dependencies.resolve(version, options), true);
}

async function main(argv = process.argv.slice(2)) {
  const result = await prepareOwnedVscodeTestCache(argument('--version', argv) || DEFAULT_VERSION, {
    checkOnly: argv.includes('--check'), adoptExisting: argv.includes('--adopt-existing')
  });
  const rendered = `${JSON.stringify(result, null, 2)}\n`;
  const output = argument('--receipt', argv);
  if (output) {
    const target = path.resolve(output);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const temporary = `${target}.${process.pid}.new`;
    fs.writeFileSync(temporary, rendered, { encoding: 'utf8', flag: 'wx' });
    fs.renameSync(temporary, target);
  }
  process.stdout.write(rendered);
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
  process.exitCode = 1;
});

module.exports = { DEFAULT_VERSION, cacheEvidence, prepareOwnedVscodeTestCache };
