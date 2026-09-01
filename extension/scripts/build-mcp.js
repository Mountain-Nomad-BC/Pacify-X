'use strict';

const path = require('path');
const fs = require('fs');
const esbuild = require('esbuild');

const root = path.resolve(__dirname, '..');
const version = String(JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version);
const output = path.join(root, 'server', 'index.js');
const check = process.argv.includes('--check');
const result = esbuild.buildSync({
  entryPoints: [path.join(root, 'server', 'source.mjs')],
  outfile: output,
  bundle: true,
  write: !check,
  platform: 'node',
  target: 'node20',
  format: 'cjs',
  sourcemap: false,
  legalComments: 'none',
  define: { __PX_EXTENSION_VERSION__: JSON.stringify(version) }
});
if (check) {
  const expected = result.outputFiles?.[0]?.contents;
  const current = fs.existsSync(output) ? fs.readFileSync(output) : null;
  if (!expected || !current || !Buffer.from(expected).equals(current)) {
    throw new Error('MCP bundle is stale; run npm run build:mcp before release identity application.');
  }
}
process.stdout.write(`${output}${check ? ' (current)' : ''}\n`);
