'use strict';

const path = require('path');
const fs = require('fs');
const esbuild = require('esbuild');

const root = path.resolve(__dirname, '..');
const version = String(JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version);
esbuild.buildSync({
  entryPoints: [path.join(root, 'server', 'source.mjs')],
  outfile: path.join(root, 'server', 'index.js'),
  bundle: true,
  platform: 'node',
  target: 'node20',
  format: 'cjs',
  sourcemap: false,
  legalComments: 'none',
  define: { __PX_EXTENSION_VERSION__: JSON.stringify(version) }
});
process.stdout.write(`${path.join(root, 'server', 'index.js')}\n`);
