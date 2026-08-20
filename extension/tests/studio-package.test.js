'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  MAX_DEPTH,
  MAX_DIRECTORIES,
  MAX_FILE_BYTES,
  MAX_FILES,
  UTF8_BOM_POLICY,
  digestFiles,
  fileInventory,
  materializeSkillPackage,
  normalizeFiles,
  readSkillPackage,
  reclaimMaterializedSkillPackage
} = require('../src/studioPackage');

const files = { 'SKILL.md': '# Skill\n', 'capability.json': '{}\n', 'skill.yaml': 'id: test\n', 'tests/case.json': '{}\n' };

test('guided skill package materialization is bounded, immutable, and deterministic', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const first = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  const second = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  assert.equal(first.reused, false); assert.equal(second.reused, true); assert.equal(first.sourceDirectory, second.sourceDirectory);
  assert.equal(fs.readFileSync(path.join(first.sourceDirectory, 'SKILL.md'), 'utf8'), '# Skill\n');
  assert.equal(first.treeSha256, second.treeSha256); assert.equal(first.fileCount, 4);
  const lifecycleRoot = path.join(root, '.px', 'studio-inputs', '.lifecycle');
  const receiptNames = fs.readdirSync(lifecycleRoot).sort();
  assert.equal(receiptNames.filter(name => name.endsWith('.registered.json')).length, 2);
  assert.equal(receiptNames.filter(name => name.endsWith('.closed.json')).length, 2);
  const closed = receiptNames.filter(name => name.endsWith('.closed.json')).map(name => JSON.parse(fs.readFileSync(path.join(lifecycleRoot, name), 'utf8')));
  assert.deepEqual(closed.map(item => item.state).sort(), ['published', 'reused']);
  assert.ok(closed.every(item => item.tree_sha256 === first.treeSha256 && item.file_count === 4));
  assert.equal(JSON.stringify(closed).includes('# Skill'), false);
  assert.deepEqual(first.materialization.files, fileInventory(normalizeFiles(files)));
});

test('guided skill package reuse requires the exact expected nonlink tree', t => {
  const extraRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-extra-')); t.after(() => fs.rmSync(extraRoot, { recursive: true, force: true }));
  const extra = materializeSkillPackage(extraRoot, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  fs.writeFileSync(path.join(extra.sourceDirectory, 'unexpected.txt'), 'not part of the attested package\n');
  assert.throws(() => materializeSkillPackage(extraRoot, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }), /existing-content-mismatch/);

  const emptyDirectoryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-directory-')); t.after(() => fs.rmSync(emptyDirectoryRoot, { recursive: true, force: true }));
  const withDirectory = materializeSkillPackage(emptyDirectoryRoot, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  fs.mkdirSync(path.join(withDirectory.sourceDirectory, 'unexpected-empty-directory'));
  assert.throws(() => materializeSkillPackage(emptyDirectoryRoot, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }), /existing-content-mismatch/);
});

test('guided skill package reuse rejects links instead of following them', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-link-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const first = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  const link = path.join(first.sourceDirectory, 'unexpected-link');
  try {
    fs.symlinkSync(path.join(first.sourceDirectory, 'SKILL.md'), link, 'file');
  } catch (error) {
    if (['EPERM', 'EACCES'].includes(error?.code)) { t.skip('The host does not permit unprivileged symlink creation.'); return; }
    throw error;
  }
  assert.throws(() => materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }), /existing-link/);
});

test('guided skill package rejects traversal, absolute paths, missing core files, and non-text content', () => {
  assert.throws(() => materializeSkillPackage('', { skill_id: 'test', version: '1.0.0', editor_files: files }), /project-root-required/);
  for (const invalid of [
    { ...files, '../escape': 'x' }, { ...files, '/absolute': 'x' }, { ...files, 'C:/absolute': 'x' },
    { 'SKILL.md': '# x', 'capability.json': '{}' }, { ...files, 'resource.bin': Buffer.from('x') }
  ]) assert.throws(() => normalizeFiles(invalid), /studio-package/);
  assert.throws(() => normalizeFiles({ ...files, 'RESOURCE.md': 'a', 'resource.md': 'b' }), /case-collision/);
  for (const invalidPath of ['resource.txt:stream', 'CON', 'aux.json', 'name.', 'name ', 'e\u0301.txt']) {
    assert.throws(() => normalizeFiles({ ...files, [invalidPath]: 'x' }), /path-invalid/);
  }
  assert.throws(() => normalizeFiles({ ...files, 'Dir/a.txt': 'a', 'dir/b.txt': 'b' }), /case-collision/);
  assert.throws(() => normalizeFiles({ ...files, branch: 'a', 'branch/leaf.txt': 'b' }), /type-collision/);
  assert.throws(() => normalizeFiles({ ...files, 'duplicate\\entry.txt': 'a', 'duplicate/entry.txt': 'b' }), /path-duplicate/);
});

test('tree commitment length-frames paths and content without delimiter aliases', () => {
  const base = normalizeFiles(files);
  const left = [...base, { relativePath: 'a', content: 'x' }, { relativePath: 'b', content: 'y\0bb\0z' }];
  const right = [...base, { relativePath: 'a', content: 'x\0b\0y' }, { relativePath: 'bb', content: 'z' }];
  assert.equal(left.length, right.length);
  assert.notEqual(digestFiles(left), digestFiles(right));
  assert.equal(digestFiles(left), digestFiles([...left].reverse()));
});

test('distinct skill identities that sanitize alike use distinct staging namespaces', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-identity-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const colon = materializeSkillPackage(root, { skill_id: 'skill:a', version: '1.0.0', editor_files: files });
  const dash = materializeSkillPackage(root, { skill_id: 'skill-a', version: '1.0.0', editor_files: files });
  assert.notEqual(colon.sourceDirectory, dash.sourceDirectory);
  assert.equal(fs.readFileSync(path.join(colon.sourceDirectory, 'SKILL.md'), 'utf8'), '# Skill\n');
  assert.equal(fs.readFileSync(path.join(dash.sourceDirectory, 'SKILL.md'), 'utf8'), '# Skill\n');
});

test('guided skill package reuse rejects an oversized actual file before reading it', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-reuse-size-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const created = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  fs.writeFileSync(path.join(created.sourceDirectory, 'SKILL.md'), Buffer.alloc(MAX_FILE_BYTES + 1, 0x61));
  assert.throws(() => materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }), /existing-bound-exceeded/);
});

test('post-write verification retains a changed unpublished tree in its contained location', { concurrency: false }, t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-post-write-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const originalWrite = fs.writeFileSync; let injected = false;
  try {
    fs.writeFileSync = (destination, ...args) => {
      const result = originalWrite(destination, ...args);
      if (!injected && path.basename(String(destination)) === 'skill.yaml' && String(destination).includes(`${path.sep}.px${path.sep}studio-inputs${path.sep}`)) {
        injected = true;
        originalWrite(path.join(path.dirname(destination), 'unexpected-after-write.txt'), 'changed after write\n');
      }
      return result;
    };
    assert.throws(
      () => materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }),
      /existing-content-mismatch/
    );
  } finally { fs.writeFileSync = originalWrite; }
  const lifecycleRoot = path.join(root, '.px', 'studio-inputs', '.lifecycle');
  const closedName = fs.readdirSync(lifecycleRoot).find(name => name.endsWith('.closed.json'));
  const closed = JSON.parse(fs.readFileSync(path.join(lifecycleRoot, closedName), 'utf8'));
  assert.equal(closed.state, 'retained-in-place'); assert.equal(closed.published_before_failure, false);
  const retained = path.join(root, closed.resource_relative);
  assert.equal(fs.existsSync(path.join(retained, 'unexpected-after-write.txt')), true);
  assert.equal(fs.existsSync(path.join(root, '.px', 'studio-inputs', '.failed')), false);
});

test('failed package retention never touches a redirected legacy .failed boundary', { concurrency: false }, t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-failed-link-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-failed-outside-')); t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  const studioRoot = path.join(root, '.px', 'studio-inputs'); fs.mkdirSync(studioRoot, { recursive: true });
  try { fs.symlinkSync(outside, path.join(studioRoot, '.failed'), process.platform === 'win32' ? 'junction' : 'dir'); } catch (error) {
    if (['EPERM', 'EACCES'].includes(error?.code)) { t.skip('The host does not permit unprivileged directory link creation.'); return; }
    throw error;
  }
  const originalWrite = fs.writeFileSync; let forced = false;
  try {
    fs.writeFileSync = (destination, ...args) => {
      if (!forced && path.basename(String(destination)) === 'SKILL.md' && String(destination).includes(`${path.sep}.px${path.sep}studio-inputs${path.sep}`)) {
        forced = true; const error = new Error('forced-publish-failure'); error.code = 'EFORCED'; throw error;
      }
      return originalWrite(destination, ...args);
    };
    assert.throws(
      () => materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }),
      /forced-publish-failure/
    );
  } finally { fs.writeFileSync = originalWrite; }
  assert.deepEqual(fs.readdirSync(outside), []);
  const lifecycleRoot = path.join(studioRoot, '.lifecycle');
  const closedName = fs.readdirSync(lifecycleRoot).find(name => name.endsWith('.closed.json'));
  const closed = JSON.parse(fs.readFileSync(path.join(lifecycleRoot, closedName), 'utf8'));
  assert.equal(closed.state, 'retained-in-place'); assert.doesNotMatch(closed.resource_relative, /\.tmp-/);
  assert.equal(fs.existsSync(path.join(root, closed.resource_relative)), true);
});

test('existing skill package reader is bounded to canonical and preserved roots', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const packageRoot = path.join(root, '.px', 'skills', 'sample'); fs.mkdirSync(packageRoot, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(packageRoot, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  const unicodeText = '# Caf\u00e9 \u2014 \u6771\u4eac \ud83d\ude80\n';
  fs.writeFileSync(path.join(packageRoot, 'SKILL.md'), unicodeText, 'utf8');
  const loaded = readSkillPackage(root, '.px/skills/sample'); assert.equal(loaded.fileCount, 4); assert.equal(loaded.editor_files['SKILL.md'], unicodeText);
  fs.mkdirSync(path.join(root, 'outside')); assert.throws(() => readSkillPackage(root, 'outside'), /read-boundary/);
  assert.throws(() => readSkillPackage(root, '../outside'), /read-path-invalid/);
});

test('existing skill package reader fails closed on malformed UTF-8', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-invalid-utf8-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const packageRoot = path.join(root, '.px', 'skills', 'invalid-utf8'); fs.mkdirSync(packageRoot, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(packageRoot, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  fs.writeFileSync(path.join(packageRoot, 'SKILL.md'), Buffer.from([0x23, 0x20, 0xc3, 0x28, 0x0a]));
  assert.throws(() => readSkillPackage(root, '.px/skills/invalid-utf8'), /read-utf8-invalid:SKILL\.md/);
});

test('existing skill package reader preserves an exact UTF-8 BOM', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-bom-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const packageRoot = path.join(root, '.px', 'skills', 'bom'); fs.mkdirSync(packageRoot, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(packageRoot, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  const original = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('# Skill\n', 'utf8')]);
  fs.writeFileSync(path.join(packageRoot, 'SKILL.md'), original);
  const loaded = readSkillPackage(root, '.px/skills/bom');
  assert.equal(UTF8_BOM_POLICY, 'preserve'); assert.equal(loaded.editor_files['SKILL.md'].codePointAt(0), 0xfeff);
  assert.equal(Buffer.from(loaded.editor_files['SKILL.md'], 'utf8').equals(original), true);
});

test('existing skill package reader rejects empty injected directory topology', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-topology-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const packageRoot = path.join(root, '.px', 'skills', 'topology'); fs.mkdirSync(packageRoot, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(packageRoot, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  fs.mkdirSync(path.join(packageRoot, 'injected-empty'));
  assert.throws(() => readSkillPackage(root, '.px/skills/topology'), /read-topology-invalid/);
});

test('existing skill package reader enforces file, directory, and depth caps before reads', t => {
  const oversizedRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-size-')); t.after(() => fs.rmSync(oversizedRoot, { recursive: true, force: true }));
  const oversizedPackage = path.join(oversizedRoot, '.px', 'skills', 'oversized'); fs.mkdirSync(oversizedPackage, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(oversizedPackage, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  fs.writeFileSync(path.join(oversizedPackage, 'SKILL.md'), Buffer.alloc(MAX_FILE_BYTES + 1, 0x61));
  assert.throws(() => readSkillPackage(oversizedRoot, '.px/skills/oversized'), /read-bound-exceeded/);

  const fileCountRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-files-')); t.after(() => fs.rmSync(fileCountRoot, { recursive: true, force: true }));
  const fileCountPackage = path.join(fileCountRoot, '.px', 'skills', 'files'); fs.mkdirSync(fileCountPackage, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(fileCountPackage, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  for (let index = 0; index <= MAX_FILES; index += 1) fs.writeFileSync(path.join(fileCountPackage, `extra-${index}.txt`), 'x');
  assert.throws(() => readSkillPackage(fileCountRoot, '.px/skills/files'), /read-bound-exceeded/);

  const directoryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-directories-')); t.after(() => fs.rmSync(directoryRoot, { recursive: true, force: true }));
  const directoryPackage = path.join(directoryRoot, '.px', 'skills', 'directories'); fs.mkdirSync(directoryPackage, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(directoryPackage, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  for (let index = 0; index <= MAX_DIRECTORIES; index += 1) fs.mkdirSync(path.join(directoryPackage, `empty-${index}`));
  assert.throws(() => readSkillPackage(directoryRoot, '.px/skills/directories'), /read-bound-exceeded/);

  const depthRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-depth-')); t.after(() => fs.rmSync(depthRoot, { recursive: true, force: true }));
  const depthPackage = path.join(depthRoot, '.px', 'skills', 'depth'); fs.mkdirSync(depthPackage, { recursive: true });
  for (const [relative, content] of Object.entries(files)) { const target = path.join(depthPackage, ...relative.split('/')); fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, content); }
  fs.mkdirSync(path.join(depthPackage, ...Array.from({ length: MAX_DEPTH + 1 }, (_, index) => `d${index}`)), { recursive: true });
  assert.throws(() => readSkillPackage(depthRoot, '.px/skills/depth'), /read-bound-exceeded/);
});

test('existing skill package reader rejects nonportable aliases before filesystem access', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-skill-reader-aliases-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const supplied of ['.px/skills/name:stream', '.px/skills/CON', '.px/skills/name.', '.px/skills/name ']) {
    assert.throws(() => readSkillPackage(root, supplied), /read-path-invalid/);
  }
});

test('shared cross-runtime tree vectors retain exact UTF-8 framing parity', () => {
  const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', '..', 'tests', 'fixtures', 'studio-skill-tree-vectors.json'), 'utf8'));
  assert.equal(fixture.schema_version, 'px.skill-tree-vectors/1.0');
  const hashes = new Map();
  for (const vector of fixture.vectors) {
    const framedRecords = vector.files.map(file => ({ relativePath: file.path, content: Buffer.from(file.content_base64, 'base64').toString('utf8') }));
    const digest = digestFiles(framedRecords);
    assert.equal(digest, vector.expected_sha256, vector.id);
    hashes.set(vector.id, digest);
  }
  assert.notEqual(hashes.get('delimiter-left'), hashes.get('delimiter-right'));
});

test('editor materialization rejects unpaired surrogates and enforces the 512 KiB per-file contract', () => {
  assert.throws(() => normalizeFiles({ ...files, 'resources/binary.txt': 'left\0right' }), /content-nul/);
  assert.throws(() => materializeSkillPackage(process.cwd(), { skill_id: 'skill:\ud800', version: '1.0.0', editor_files: files }), /skill-id-invalid/);
  assert.throws(() => normalizeFiles({ ...files, 'resources/\ud800.txt': 'x' }), /path-invalid/);
  assert.throws(() => normalizeFiles({ ...files, 'resources/value.txt': '\udc00' }), /unpaired-surrogate/);
  assert.doesNotThrow(() => normalizeFiles({ ...files, 'resources/emoji-\ud83d\ude80.txt': 'paired \ud83d\ude80\n' }));
  assert.doesNotThrow(() => normalizeFiles({ ...files, 'resources/max.txt': 'a'.repeat(MAX_FILE_BYTES) }));
  assert.throws(() => normalizeFiles({ ...files, 'resources/too-large.txt': 'a'.repeat(MAX_FILE_BYTES + 1) }), /file-bytes-exceeded/);
});

test('materialization never overwrites a pre-existing incomplete target', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-no-clobber-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const created = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  fs.rmSync(created.sourceDirectory, { recursive: true, force: false });
  fs.mkdirSync(created.sourceDirectory, { recursive: true });
  fs.writeFileSync(path.join(created.sourceDirectory, 'owner.txt'), 'external owner\n');
  assert.throws(() => materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files }), /existing-content-mismatch/);
  assert.equal(fs.readFileSync(path.join(created.sourceDirectory, 'owner.txt'), 'utf8'), 'external owner\n');
  assert.equal(fs.existsSync(path.join(created.sourceDirectory, 'SKILL.md')), false);
});

test('receipt-bound successful reclamation removes only the exact materialized source', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-reclaim-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const materialized = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  const createReceipt = { schema_version: 'px.skill-draft/1.1', created: true, source_authority_token: 'source-token', source_tree_sha256: materialized.treeSha256, file_count: materialized.fileCount, files: materialized.materialization.files };
  const reclaimed = reclaimMaterializedSkillPackage(root, materialized, createReceipt);
  assert.equal(reclaimed.reclaimed, true); assert.equal(fs.existsSync(materialized.sourceDirectory), false);
  const lifecycleRoot = path.join(root, '.px', 'studio-inputs', '.lifecycle');
  assert.equal(fs.existsSync(path.join(lifecycleRoot, `${materialized.materialization.operation_id}.reclaim-authorized.json`)), true);
  assert.equal(fs.existsSync(path.join(lifecycleRoot, `${materialized.materialization.operation_id}.reclaimed.json`)), true);
});

test('failed reclamation retains the exact materialized source for evidence', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-package-reclaim-retain-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const materialized = materializeSkillPackage(root, { skill_id: 'my-skill', version: '1.0.0', editor_files: files });
  const mismatched = { schema_version: 'px.skill-draft/1.1', created: true, source_authority_token: 'source-token', source_tree_sha256: 'f'.repeat(64), file_count: materialized.fileCount, files: materialized.materialization.files };
  assert.throws(() => reclaimMaterializedSkillPackage(root, materialized, mismatched), /create-receipt-mismatch/);
  assert.equal(fs.existsSync(path.join(materialized.sourceDirectory, 'SKILL.md')), true);
});
