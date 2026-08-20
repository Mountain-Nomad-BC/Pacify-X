'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const crypto = require('crypto');
const esbuild = require('esbuild');

const root = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const packagedPkg = { ...pkg, main: './src/extension.bundle.js' };
const output = path.join(root, 'dist', `${pkg.name}-${pkg.version}.vsix`);
const issuedCustodyRoot = path.join(root, '..', '.engineering-bootstrap', 'quarantine', 'release-artifacts', 'vscode');
const issuedName = path.basename(output);
if (fs.existsSync(output) || findIssuedArtifacts(issuedCustodyRoot, issuedName).length) {
  throw new Error(`Refusing to overwrite issued extension version ${pkg.version}; bump package.version before creating changed VSIX bytes.`);
}
const extensionBundle = esbuild.buildSync({
  absWorkingDir: root,
  entryPoints: ['src/extension.js'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  external: ['vscode'],
  legalComments: 'none'
}).outputFiles[0].contents;

const contentTypes = `<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="vsixmanifest" ContentType="text/xml"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="js" ContentType="application/javascript"/>
  <Default Extension="css" ContentType="text/css"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="md" ContentType="text/markdown"/>
  <Default Extension="txt" ContentType="text/plain"/>
</Types>
`;

const manifest = `<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="${xml(pkg.name)}" Version="${xml(pkg.version)}" Publisher="${xml(pkg.publisher)}"/>
    <DisplayName>${xml(pkg.displayName)}</DisplayName>
    <Description xml:space="preserve">${xml(pkg.description)}</Description>
    <Tags>${xml((pkg.keywords || []).join(','))}</Tags>
    <Categories>${xml((pkg.categories || []).join(','))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="${xml(pkg.engines.vscode)}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/>
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" Version="[1.132.0,)"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.License" Path="extension/LICENSE" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/media/px-shield-128.png" Addressable="true"/>
  </Assets>
</PackageManifest>
`;

function xml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[character]));
}

function findIssuedArtifacts(directory, name, budget = { remaining: 4096 }) {
  if (!fs.existsSync(directory) || budget.remaining <= 0) return [];
  const found = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if ((budget.remaining -= 1) < 0) break;
    const full = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) found.push(...findIssuedArtifacts(full, name, budget));
    else if (entry.isFile() && entry.name === name) found.push(full);
  }
  return found;
}

function walk(directory, relative = '') {
  const result = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const rel = path.posix.join(relative, entry.name);
    const full = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) result.push(...walk(full, rel));
    else if (entry.isFile()) result.push({ name: `extension/${rel}`, data: fs.readFileSync(full), modified: fs.statSync(full).mtime });
  }
  return result;
}

const entries = [
  { name: '[Content_Types].xml', data: Buffer.from(contentTypes), modified: new Date() },
  { name: 'extension.vsixmanifest', data: Buffer.from(manifest), modified: new Date() },
  { name: 'extension/package.json', data: Buffer.from(`${JSON.stringify(packagedPkg, null, 2)}\n`), modified: fs.statSync(path.join(root, 'package.json')).mtime },
  { name: 'extension/src/extension.bundle.js', data: extensionBundle, modified: new Date() }
];
for (const directory of ['src', 'media', 'docs', 'resources']) {
  const full = path.join(root, directory);
  if (fs.existsSync(full)) entries.push(...walk(full, directory));
}
const mcpBundle = path.join(root, 'server', 'index.js');
if (fs.existsSync(mcpBundle)) entries.push({ name: 'extension/server/index.js', data: fs.readFileSync(mcpBundle), modified: fs.statSync(mcpBundle).mtime });
for (const file of ['README.md', 'CHANGELOG.md', 'LICENSE', 'NOTICE']) {
  const full = path.join(root, file);
  if (fs.existsSync(full)) entries.push({ name: `extension/${file}`, data: fs.readFileSync(full), modified: fs.statSync(full).mtime });
}

const table = crcTable();
const locals = [];
const centrals = [];
let offset = 0;
for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
  const name = Buffer.from(entry.name.replaceAll('\\', '/'));
  const compressed = zlib.deflateRawSync(entry.data, { level: 9 });
  const crc = crc32(entry.data, table);
  const { date, time } = dosDate(entry.modified);
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 6); local.writeUInt16LE(8, 8);
  local.writeUInt16LE(time, 10); local.writeUInt16LE(date, 12); local.writeUInt32LE(crc, 14);
  local.writeUInt32LE(compressed.length, 18); local.writeUInt32LE(entry.data.length, 22); local.writeUInt16LE(name.length, 26); local.writeUInt16LE(0, 28);
  locals.push(local, name, compressed);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(0, 8); central.writeUInt16LE(8, 10);
  central.writeUInt16LE(time, 12); central.writeUInt16LE(date, 14); central.writeUInt32LE(crc, 16);
  central.writeUInt32LE(compressed.length, 20); central.writeUInt32LE(entry.data.length, 24); central.writeUInt16LE(name.length, 28);
  central.writeUInt16LE(0, 30); central.writeUInt16LE(0, 32); central.writeUInt16LE(0, 34); central.writeUInt16LE(0, 36); central.writeUInt32LE(0, 38); central.writeUInt32LE(offset, 42);
  centrals.push(central, name);
  offset += local.length + name.length + compressed.length;
}
const centralSize = centrals.reduce((sum, item) => sum + item.length, 0);
const end = Buffer.alloc(22);
end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(0, 4); end.writeUInt16LE(0, 6);
end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(centralSize, 12); end.writeUInt32LE(offset, 16); end.writeUInt16LE(0, 20);
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, Buffer.concat([...locals, ...centrals, end]));
const digest = crypto.createHash('sha256').update(fs.readFileSync(output)).digest('hex');
fs.writeFileSync(path.join(root, 'SHA256SUMS.txt'), `${digest}  dist/${path.basename(output)}\n`, 'utf8');
process.stdout.write(`${output}\nSHA256 ${digest}\n`);

function dosDate(input) {
  const date = new Date(input);
  const year = Math.max(1980, date.getFullYear());
  return { time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2), date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate() };
}
function crcTable() {
  const values = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    values[index] = value >>> 0;
  }
  return values;
}
function crc32(buffer, values) {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = values[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
