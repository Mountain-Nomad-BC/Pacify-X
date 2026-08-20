'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { buildUiActionInventory } = require('../src/uiActionInventory');

const root = path.resolve(__dirname, '..');
const target = path.join(root, 'resources', 'ui', 'action-inventory.json');
const sources = fs.readdirSync(path.join(root, 'media', 'dashboard')).filter(name => name.endsWith('.js')).map(name => path.join(root, 'media', 'dashboard', name));

function discoveredActions() {
  const actions = new Map();
  for (const file of sources) {
    const relative = path.relative(root, file).replaceAll('\\', '/');
    const source = fs.readFileSync(file, 'utf8');
    for (const match of source.matchAll(/data-action=["']([A-Za-z][A-Za-z0-9]*)["']/g)) {
      if (!actions.has(match[1])) actions.set(match[1], new Set());
      actions.get(match[1]).add(relative);
    }
  }
  return actions;
}

function build() {
  const declared = buildUiActionInventory();
  const discovered = discoveredActions();
  const missing = [...discovered.keys()].filter(action => !declared[action]);
  const stale = Object.keys(declared).filter(action => !discovered.has(action));
  if (missing.length || stale.length) throw new Error(`ui-action-inventory-mismatch missing=${missing.join(',') || 'none'} stale=${stale.join(',') || 'none'}`);
  return {
    schema_version: 'pacify-x.ui-action-inventory.v1',
    authority: 'generated from rendered data-action controls; effects remain host-authoritative',
    navigation_controls: { selector: '[data-surface]', mode: 'ui-only', effect: 'none-outside-webview', acknowledgement: 'active surface and focus update' },
    action_count: discovered.size,
    actions: [...discovered.keys()].sort().map(action => ({ ...declared[action], rendered_in: [...discovered.get(action)].sort() }))
  };
}

function serialized() { return `${JSON.stringify(build(), null, 2)}\n`; }

if (require.main === module) {
  if (process.argv.includes('--check')) {
    const expected = serialized();
    const actual = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : '';
    if (actual !== expected) { console.error('resources/ui/action-inventory.json is stale; run npm run build:ui-actions'); process.exitCode = 1; }
  } else {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, serialized(), 'utf8');
    console.log(path.relative(root, target));
  }
}

module.exports = { build, discoveredActions, serialized };
