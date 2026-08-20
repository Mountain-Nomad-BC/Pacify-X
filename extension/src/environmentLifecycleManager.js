'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const MAX_ENTRIES = 50000;
function sha(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function within(candidate, root) { const relative = path.relative(path.resolve(root), path.resolve(candidate)); return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative)); }
function safeId(value) { return String(value || '').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 100) || 'resource'; }

function identity(stat) { return `${Number(stat.dev)}:${Number(stat.ino)}`; }
function assertNoParentAliases(target, root) {
  const relative = path.relative(root, target); let cursor = root;
  for (const component of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, component);
    if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error('Lifecycle target contains a symbolic link or junction alias in its path.');
  }
}

function metadataSnapshot(target, allowedRoot) {
  const absolute = path.resolve(target); const root = path.resolve(allowedRoot);
  if (!within(absolute, root) || absolute === root) throw new Error('Lifecycle target is outside or equal to its admitted root.');
  const rootReal = fs.realpathSync.native(root); assertNoParentAliases(absolute, root);
  const real = fs.realpathSync.native(absolute); if (!within(real, rootReal) || real === rootReal) throw new Error('Lifecycle target real path escaped its admitted root.');
  const rootStat = fs.lstatSync(absolute); if (rootStat.isSymbolicLink()) throw new Error('Lifecycle target cannot be a symbolic link or junction alias.');
  const records = []; const pending = [{ absolute, relative: '.' }];
  while (pending.length) {
    if (records.length >= MAX_ENTRIES) throw new Error('Lifecycle snapshot exceeded its entry bound.');
    const current = pending.shift(); const stat = fs.lstatSync(current.absolute);
    if (stat.isSymbolicLink()) throw new Error('Lifecycle target contains a symbolic link or junction alias.');
    records.push({ path: current.relative, type: stat.isDirectory() ? 'directory' : stat.isFile() ? 'file' : 'other', size: stat.size, modified_ms: Math.trunc(stat.mtimeMs), device: Number(stat.dev), inode: Number(stat.ino) });
    if (stat.isDirectory()) {
      const children = fs.readdirSync(current.absolute, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
      for (const child of children) pending.push({ absolute: path.join(current.absolute, child.name), relative: current.relative === '.' ? child.name : `${current.relative}/${child.name}` });
    }
  }
  return { absolute, real, root, root_real: rootReal, root_identity: identity(fs.statSync(rootReal)), target_identity: identity(fs.statSync(real)), entry_count: records.length, metadata_sha256: sha(records), records };
}

class EnvironmentLifecycleManager {
  constructor(projectRoot) {
    this.projectRoot = path.resolve(projectRoot);
    this.quarantineRoot = path.join(this.projectRoot, '.engineering-bootstrap', 'quarantine', 'environment');
    this.receiptRoot = path.join(this.projectRoot, '.engineering-bootstrap', 'environment', 'lifecycle-receipts');
    this.pending = new Map();
  }
  preview(record, action = 'quarantine') {
    if (!record?.id) throw new Error('Lifecycle record identity is required.');
    if (record.executable || record.resource_type === 'system-tool') return { allowed: false, reason: 'externally-owned-system-tool', handoff: 'Use the detected install source/package manager through a separately admitted updater.' };
    if (!['quarantine', 'archive'].includes(action)) throw new Error('Lifecycle action is not admitted.');
    const target = path.resolve(record.path || record.directory || '');
    if (record.active || record.state === 'active' || record.state === 'wrong-version') return { allowed: false, reason: 'resource-active-or-selected', target };
    const first = metadataSnapshot(target, this.projectRoot); const second = metadataSnapshot(target, this.projectRoot);
    if (first.metadata_sha256 !== second.metadata_sha256) return { allowed: false, reason: 'snapshot-changed', target };
    const consumers = [...new Set((record.variables || []).flatMap(variable => variable.consumers || []).map(item => item.path).filter(Boolean))].sort();
    const token = crypto.randomUUID();
    const preview = { schema_version: 'px.environment-lifecycle-preview/1.0', token, record_id: record.id, resource_kind: record.kind || record.resource_type || 'unknown', action, target, target_relative: path.relative(this.projectRoot, target).split(path.sep).join('/'), snapshot_sha256: first.metadata_sha256, entry_count: first.entry_count, active_use: false, consumers, consumer_ack_required: consumers.length > 0, disposition: 'reversible-project-owned-quarantine', exact_confirmation: target, allowed: true };
    this.pending.set(token, { preview, snapshot: first }); return preview;
  }
  execute(token, confirmation) {
    const pending = this.pending.get(token); if (!pending) throw new Error('Lifecycle preview token is unknown or already consumed.');
    const { preview, snapshot } = pending;
    if (!confirmation?.approved || confirmation.exact_target !== preview.exact_confirmation) throw new Error('Lifecycle action requires exact-target confirmation.');
    if (preview.consumer_ack_required && !confirmation.consumer_impact_acknowledged) throw new Error('Lifecycle action requires consumer-impact acknowledgement.');
    const immediate = metadataSnapshot(preview.target, this.projectRoot); if (immediate.metadata_sha256 !== snapshot.metadata_sha256 || immediate.real !== snapshot.real || immediate.root_real !== snapshot.root_real || immediate.root_identity !== snapshot.root_identity || immediate.target_identity !== snapshot.target_identity) throw new Error('Lifecycle target changed after preview.');
    fs.mkdirSync(this.quarantineRoot, { recursive: true });
    const quarantineReal = fs.realpathSync.native(this.quarantineRoot); if (!within(quarantineReal, snapshot.root_real)) throw new Error('Lifecycle quarantine real path escaped the admitted project root.');
    assertNoParentAliases(this.quarantineRoot, this.projectRoot);
    if (Number(fs.statSync(quarantineReal).dev) !== Number(fs.statSync(snapshot.real).dev)) throw new Error('Lifecycle quarantine requires a same-device reversible move.');
    const destination = path.join(this.quarantineRoot, `${safeId(preview.record_id)}-${Date.now()}`); if (!within(destination, this.quarantineRoot)) throw new Error('Lifecycle quarantine destination escaped its root.');
    fs.renameSync(preview.target, destination); this.pending.delete(token);
    const receipt = { schema_version: 'px.environment-lifecycle-receipt/1.1', receipt_id: `env-life-${crypto.randomUUID()}`, timestamp: new Date().toISOString(), record_id: preview.record_id, resource_kind: preview.resource_kind, action: preview.action, source_relative: preview.target_relative, destination_relative: path.relative(this.projectRoot, destination).split(path.sep).join('/'), snapshot_sha256: preview.snapshot_sha256, source_identity: snapshot.target_identity, root_identity: snapshot.root_identity, same_device_move: true, entry_count: preview.entry_count, consumer_count: preview.consumers.length, consumer_impact_acknowledged: Boolean(confirmation.consumer_impact_acknowledged), disposition: 'quarantined-reversible', values_or_content_retained_in_receipt: false };
    fs.mkdirSync(this.receiptRoot, { recursive: true }); fs.writeFileSync(path.join(this.receiptRoot, `${receipt.receipt_id}.json`), `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' }); return receipt;
  }
}

module.exports = { MAX_ENTRIES, within, metadataSnapshot, EnvironmentLifecycleManager };
