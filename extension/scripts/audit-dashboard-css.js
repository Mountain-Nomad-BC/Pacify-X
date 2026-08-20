'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const stylesRoot = path.join(root, 'media', 'styles');
const baselinePath = path.join(root, 'resources', 'ui', 'css-audit-baseline.json');

function cssFiles() {
  const layers = fs.readdirSync(stylesRoot).filter(name => name.endsWith('.css')).sort().map(name => path.join(stylesRoot, name));
  return [...layers, path.join(root, 'media', 'dashboard.css')];
}

function splitSelectors(value) {
  const selectors = [];
  let start = 0;
  let depth = 0;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === '(' || character === '[') depth += 1;
    if (character === ')' || character === ']') depth = Math.max(0, depth - 1);
    if (character === ',' && depth === 0) {
      selectors.push(value.slice(start, index));
      start = index + 1;
    }
  }
  selectors.push(value.slice(start));
  return selectors;
}

function selectorsFromCss(source) {
  const css = source.replace(/\/\*[\s\S]*?\*\//g, '');
  const selectors = [];
  let boundary = -1;
  let quote = '';
  for (let index = 0; index < css.length; index += 1) {
    const character = css[index];
    if (quote) {
      if (character === quote && css[index - 1] !== '\\') quote = '';
      continue;
    }
    if (character === '"' || character === "'") { quote = character; continue; }
    if (character === '{') {
      const prelude = css.slice(boundary + 1, index).trim();
      if (prelude && !prelude.startsWith('@')) {
        for (const selector of splitSelectors(prelude)) {
          const normalized = selector.trim().replace(/\s+/g, ' ').replace(/\s*([>+~])\s*/g, '$1');
          if (normalized && !/^(from|to|\d+%)$/.test(normalized)) selectors.push(normalized);
        }
      }
      boundary = index;
    } else if (character === '}' || character === ';') {
      boundary = index;
    }
  }
  return selectors;
}

function scopedSelectorsFromCss(source) {
  const css = source.replace(/\/\*[\s\S]*?\*\//g, ''); const records = []; const stack = [];
  let boundary = -1; let quote = '';
  for (let index = 0; index < css.length; index += 1) {
    const character = css[index];
    if (quote) { if (character === quote && css[index - 1] !== '\\') quote = ''; continue; }
    if (character === '"' || character === "'") { quote = character; continue; }
    if (character === '{') {
      const prelude = css.slice(boundary + 1, index).trim();
      if (prelude.startsWith('@')) stack.push(/^@(media|supports|container)\b/i.test(prelude) ? prelude.replace(/\s+/g, ' ') : '');
      else {
        const scope = stack.filter(Boolean).join(' > ');
        for (const selector of splitSelectors(prelude)) {
          const normalized = selector.trim().replace(/\s+/g, ' ').replace(/\s*([>+~])\s*/g, '$1');
          if (normalized && !/^(from|to|\d+%)$/.test(normalized)) records.push({ selector: normalized, scope });
        }
        stack.push('');
      }
      boundary = index;
    } else if (character === '}') { stack.pop(); boundary = index; }
    else if (character === ';') boundary = index;
  }
  return records;
}

function contrastRatio(foreground, background) {
  const channel = value => {
    const normalized = value / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  const luminance = value => {
    const bytes = value.match(/[a-f0-9]{2}/gi).map(item => parseInt(item, 16));
    return 0.2126 * channel(bytes[0]) + 0.7152 * channel(bytes[1]) + 0.0722 * channel(bytes[2]);
  };
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

function contrastChecks() {
  const tokenSource = fs.readFileSync(path.join(stylesRoot, '01-tokens.css'), 'utf8');
  const token = name => tokenSource.match(new RegExp(`${name}:\\s*(#[a-f0-9]{6})`, 'i'))?.[1];
  const foregrounds = ['--px-color-text-muted', '--px-color-text-faint'];
  const backgrounds = ['#05080d', '#101925', '#07111b'];
  return foregrounds.flatMap(name => backgrounds.map(background => {
    const foreground = token(name);
    return { token: name, foreground, background, ratio: foreground ? Number(contrastRatio(foreground, background).toFixed(3)) : 0, required: 4.5 };
  }));
}

function audit(files = cssFiles()) {
  const occurrences = new Map();
  const perFile = [];
  for (const file of files) {
    const relative = path.relative(root, file).replaceAll('\\', '/');
    const selectors = scopedSelectorsFromCss(fs.readFileSync(file, 'utf8'));
    perFile.push({ file: relative, selector_occurrences: selectors.length, unique_selectors: new Set(selectors.map(item => `${item.scope}\u0000${item.selector}`)).size });
    for (const record of selectors) {
      const key = `${record.scope}\u0000${record.selector}`; const records = occurrences.get(key) || [];
      records.push(relative);
      occurrences.set(key, records);
    }
  }
  const duplicates = [...occurrences.entries()]
    .filter(([, locations]) => locations.length > 1)
    .map(([key, locations]) => { const [scope, selector] = key.split('\u0000'); return { selector, scope: scope || 'unscoped', occurrences: locations.length, files: [...new Set(locations)] }; })
    .sort((left, right) => right.occurrences - left.occurrences || left.selector.localeCompare(right.selector));
  const crossFileDuplicates = duplicates.filter(item => item.files.length > 1);
  return {
    schema_version: 'px.ui-css-selector-audit/1.1',
    files: perFile,
    selector_occurrences: perFile.reduce((sum, item) => sum + item.selector_occurrences, 0),
    unique_selectors: occurrences.size,
    duplicate_selector_count: duplicates.length,
    duplicate_occurrences: duplicates.reduce((sum, item) => sum + item.occurrences - 1, 0),
    cross_file_duplicate_selector_count: crossFileDuplicates.length,
    cross_file_duplicate_occurrences: crossFileDuplicates.reduce((sum, item) => sum + item.occurrences - 1, 0),
    duplicates
  };
}

function check(report) {
  const baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
  const failures = [];
  for (const metric of ['duplicate_selector_count', 'duplicate_occurrences', 'cross_file_duplicate_selector_count', 'cross_file_duplicate_occurrences']) {
    if (report[metric] > baseline.maximums[metric]) failures.push(`${metric} ${report[metric]} exceeds ${baseline.maximums[metric]}`);
  }
  const layerOrder = fs.readFileSync(path.join(stylesRoot, '00-layer-order.css'), 'utf8').trim();
  if (layerOrder !== baseline.required_layer_order) failures.push('CSS layer order differs from the admitted order.');
  for (const item of contrastChecks()) if (item.ratio < item.required) failures.push(`${item.token} contrast ${item.ratio}:1 on ${item.background} is below ${item.required}:1`);
  if (failures.length) throw new Error(`Dashboard CSS audit failed: ${failures.join('; ')}`);
  return { valid: true, baseline: baseline.schema_version };
}

if (require.main === module) {
  const report = audit();
  if (process.argv.includes('--check')) {
    process.stdout.write(`${JSON.stringify({
      schema_version: report.schema_version,
      selector_occurrences: report.selector_occurrences,
      unique_selectors: report.unique_selectors,
      duplicate_selector_count: report.duplicate_selector_count,
      duplicate_occurrences: report.duplicate_occurrences,
      cross_file_duplicate_selector_count: report.cross_file_duplicate_selector_count,
      cross_file_duplicate_occurrences: report.cross_file_duplicate_occurrences,
      top_duplicates: report.duplicates.slice(0, 10),
      contrast_checks: contrastChecks(),
      check: check(report)
    }, null, 2)}\n`);
  } else {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  }
}

module.exports = { audit, check, contrastChecks, contrastRatio, cssFiles, scopedSelectorsFromCss, selectorsFromCss, splitSelectors };
