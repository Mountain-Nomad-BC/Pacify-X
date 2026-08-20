'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { scopedSelectorsFromCss, splitSelectors } = require('./audit-dashboard-css');

const root = path.resolve(__dirname, '..');
const stylesRoot = path.join(root, 'media', 'styles');
const legacyPath = path.join(root, 'media', 'dashboard.css');

function normalizeSelector(selector) {
  return selector.trim().replace(/\s+/g, ' ').replace(/\s*([>+~])\s*/g, '$1');
}

function modularOwners() {
  const owners = new Set();
  for (const name of fs.readdirSync(stylesRoot).filter(item => item.endsWith('.css')).sort()) {
    const source = fs.readFileSync(path.join(stylesRoot, name), 'utf8');
    for (const record of scopedSelectorsFromCss(source)) owners.add(`${record.scope === 'unscoped' ? '' : record.scope}\u0000${record.selector}`);
  }
  return owners;
}

function matchingBrace(source, opening) {
  let depth = 0; let quote = ''; let comment = false;
  for (let index = opening; index < source.length; index += 1) {
    const character = source[index]; const next = source[index + 1];
    if (comment) { if (character === '*' && next === '/') { comment = false; index += 1; } continue; }
    if (!quote && character === '/' && next === '*') { comment = true; index += 1; continue; }
    if (quote) { if (character === quote && source[index - 1] !== '\\') quote = ''; continue; }
    if (character === '"' || character === "'") { quote = character; continue; }
    if (character === '{') depth += 1;
    if (character === '}' && --depth === 0) return index;
  }
  throw new Error(`Unclosed CSS block at offset ${opening}.`);
}

function nextOpeningBrace(source, start, end) {
  let quote = ''; let comment = false;
  for (let index = start; index < end; index += 1) {
    const character = source[index]; const next = source[index + 1];
    if (comment) { if (character === '*' && next === '/') { comment = false; index += 1; } continue; }
    if (!quote && character === '/' && next === '*') { comment = true; index += 1; continue; }
    if (quote) { if (character === quote && source[index - 1] !== '\\') quote = ''; continue; }
    if (character === '"' || character === "'") { quote = character; continue; }
    if (character === '{') return index;
  }
  return -1;
}

function splitLeadingTrivia(prelude) {
  const match = /^(\s*(?:\/\*[\s\S]*?\*\/\s*)*)/.exec(prelude);
  const leading = match?.[1] || '';
  return { leading, rule: prelude.slice(leading.length).trim() };
}

function canonicalize(source, owners) {
  let removed = 0;
  function rewrite(start, end, scopes) {
    let cursor = start; let output = '';
    while (cursor < end) {
      const opening = nextOpeningBrace(source, cursor, end);
      if (opening < 0) { output += source.slice(cursor, end); break; }
      const closing = matchingBrace(source, opening);
      if (closing >= end) throw new Error(`CSS block at ${opening} crosses its parent boundary.`);
      const rawPrelude = source.slice(cursor, opening);
      const { leading, rule } = splitLeadingTrivia(rawPrelude);
      if (!rule) { output += source.slice(cursor, closing + 1); cursor = closing + 1; continue; }
      if (rule.startsWith('@')) {
        const scoped = /^@(media|supports|container)\b/i.test(rule) ? [...scopes, rule.replace(/\s+/g, ' ')] : scopes;
        const recursive = /^@(layer|media|supports|container)\b/i.test(rule);
        output += `${leading}${rule}{${recursive ? rewrite(opening + 1, closing, scoped) : source.slice(opening + 1, closing)}}`;
      } else {
        const scope = scopes.filter(Boolean).join(' > ');
        const kept = [];
        for (const selector of splitSelectors(rule)) {
          const normalized = normalizeSelector(selector);
          if (owners.has(`${scope}\u0000${normalized}`)) removed += 1;
          else kept.push(selector.trim());
        }
        if (kept.length) output += `${leading}${kept.join(', ')}{${source.slice(opening + 1, closing)}}`;
        else output += leading;
      }
      cursor = closing + 1;
    }
    return output;
  }
  return { source: rewrite(0, source.length, []), removed };
}

function run(write = false) {
  const original = fs.readFileSync(legacyPath, 'utf8');
  const result = canonicalize(original, modularOwners());
  if (write && result.source !== original) fs.writeFileSync(legacyPath, result.source, 'utf8');
  return { changed: result.source !== original, removed_selector_branches: result.removed, bytes_before: Buffer.byteLength(original), bytes_after: Buffer.byteLength(result.source) };
}

if (require.main === module) {
  const write = process.argv.includes('--write');
  const result = run(write);
  process.stdout.write(`${JSON.stringify({ ...result, mode: write ? 'write' : 'check' }, null, 2)}\n`);
  if (!write && result.changed) process.exitCode = 1;
}

module.exports = { canonicalize, modularOwners, normalizeSelector, run };
