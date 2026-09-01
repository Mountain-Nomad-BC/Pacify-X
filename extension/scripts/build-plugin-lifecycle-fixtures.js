'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const extensionRoot = path.resolve(__dirname, '..');
const sourceRoot = path.join(extensionRoot, 'tests', 'fixtures', 'plugin-lifecycle');
const outputRoot = path.join(extensionRoot, 'tests', 'generated', 'plugin-lifecycle');
const fixedDate = new Date('2020-01-02T03:04:06Z');

function xml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[character]));
}

function contentTypes() {
  return Buffer.from('<?xml version="1.0" encoding="utf-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="vsixmanifest" ContentType="text/xml"/><Default Extension="json" ContentType="application/json"/><Default Extension="js" ContentType="application/javascript"/></Types>\n');
}

function manifest(pkg) {
  return Buffer.from(`<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata><Identity Language="en-US" Id="${xml(pkg.name)}" Version="${xml(pkg.version)}" Publisher="${xml(pkg.publisher)}"/><DisplayName>${xml(pkg.displayName)}</DisplayName><Description xml:space="preserve">${xml(pkg.description)}</Description><Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="${xml(pkg.engines.vscode)}"/></Properties></Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" Version="[1.132.0,)"/></Installation><Dependencies/>
  <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>
`);
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

function dosDate(input) {
  const year = Math.max(1980, input.getUTCFullYear());
  return {
    time: (input.getUTCHours() << 11) | (input.getUTCMinutes() << 5) | Math.floor(input.getUTCSeconds() / 2),
    date: ((year - 1980) << 9) | ((input.getUTCMonth() + 1) << 5) | input.getUTCDate()
  };
}

function zip(entries) {
  const table = crcTable();
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const name = Buffer.from(entry.name, 'utf8');
    const compressed = zlib.deflateRawSync(entry.data, { level: 9 });
    const crc = crc32(entry.data, table);
    const { date, time } = dosDate(fixedDate);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 6); local.writeUInt16LE(8, 8);
    local.writeUInt16LE(time, 10); local.writeUInt16LE(date, 12); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18); local.writeUInt32LE(entry.data.length, 22); local.writeUInt16LE(name.length, 26);
    locals.push(local, name, compressed);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(0, 8); central.writeUInt16LE(8, 10);
    central.writeUInt16LE(time, 12); central.writeUInt16LE(date, 14); central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20); central.writeUInt32LE(entry.data.length, 24); central.writeUInt16LE(name.length, 28); central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += local.length + name.length + compressed.length;
  }
  const centralSize = centrals.reduce((sum, item) => sum + item.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(centralSize, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, ...centrals, end]);
}

function build(versionDirectory) {
  const root = path.join(sourceRoot, versionDirectory);
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  if (`${pkg.publisher}.${pkg.name}` !== 'px-owned.fixture') throw new Error('Fixture extension identity must remain px-owned.fixture');
  if (!['1.0.0', '2.0.0'].includes(pkg.version)) throw new Error(`Unsupported fixture version ${pkg.version}`);
  const entries = [
    { name: '[Content_Types].xml', data: contentTypes() },
    { name: 'extension.vsixmanifest', data: manifest(pkg) },
    { name: 'extension/package.json', data: Buffer.from(`${JSON.stringify(pkg, null, 2)}\n`) },
    { name: 'extension/extension.js', data: fs.readFileSync(path.join(root, 'extension.js')) }
  ];
  const bytes = zip(entries);
  const output = path.join(outputRoot, `px-owned.fixture-${pkg.version}.vsix`);
  fs.mkdirSync(outputRoot, { recursive: true });
  fs.writeFileSync(output, bytes);
  return { path: path.relative(extensionRoot, output).replaceAll('\\', '/'), version: pkg.version, size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
}

const artifacts = ['v1', 'v2'].map(build);
const receipt = { schema_version: 'px.plugin-lifecycle-fixtures/1.0', extension_id: 'px-owned.fixture', deterministic_timestamp_utc: fixedDate.toISOString(), artifacts };
fs.writeFileSync(path.join(outputRoot, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
