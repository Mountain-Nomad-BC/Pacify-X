'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const MAX_BYTES = 16 * 1024 * 1024;

function rejectLinks(target) {
  let cursor = path.resolve(target);
  while (true) {
    try { if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error('task-state-linked-path'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = path.dirname(cursor); if (parent === cursor) break; cursor = parent;
  }
}

function readObject(file) {
  rejectLinks(file);
  if (!fs.existsSync(file)) return null;
  if (fs.statSync(file).size > MAX_BYTES) throw new Error('task-state-byte-budget');
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('task-state-object-required');
  return value;
}

class DurableTaskState {
  constructor(projectRoot) {
    rejectLinks(projectRoot);
    this.root = fs.realpathSync(projectRoot);
    this.directory = path.join(this.root, '.agentic_engineering_os_px', 'runtime-core', 'agent-console');
    this.file = path.join(this.directory, 'task-state.json'); this.lock = path.join(this.directory, 'writer.lock');
    this.revision = 0; this.epoch = 0; this.token = crypto.randomUUID();
    this.synchronous = true;
  }

  load() {
    const value = readObject(this.file);
    if (value) {
      if (value.schemaVersion !== 'px.agent-task-store/2.0' || !Number.isSafeInteger(value.revision) || value.revision < 1 || !Number.isSafeInteger(value.epoch) || value.epoch < 1) throw new Error('task-state-invalid-generation');
      this.revision = value.revision; this.epoch = value.epoch;
    }
    return value;
  }

  _acquire() {
    rejectLinks(this.directory); fs.mkdirSync(this.directory, { recursive: true }); rejectLinks(this.directory);
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const fd = fs.openSync(this.lock, 'wx');
        try { fs.writeFileSync(fd, JSON.stringify({ schemaVersion: 'px.task-state-lease/1.0', pid: process.pid, token: this.token })); fs.fsyncSync(fd); }
        finally { fs.closeSync(fd); }
        return;
      } catch (error) {
        if (error.code !== 'EEXIST') throw error;
        const lease = readObject(this.lock);
        if (lease?.schemaVersion !== 'px.task-state-lease/1.0' || !Number.isSafeInteger(lease.pid) || lease.pid < 1 || typeof lease.token !== 'string') throw new Error('task-state-unrecognized-writer-lease');
        let alive = true;
        try { process.kill(lease.pid, 0); } catch (probe) { if (probe.code === 'ESRCH') alive = false; }
        if (alive) throw new Error('task-state-writer-busy');
        // Preserve the exact dead-writer lease; unknown/live leases are never removed.
        const recovery = path.join(this.directory, '.lock-recovery-receipts');
        rejectLinks(recovery); fs.mkdirSync(recovery, { recursive: true });
        const current = readObject(this.lock);
        if (JSON.stringify(current) !== JSON.stringify(lease)) throw new Error('task-state-writer-changed');
        fs.renameSync(this.lock, path.join(recovery, `${crypto.randomUUID()}.json`));
      }
    }
    throw new Error('task-state-writer-lock-unavailable');
  }

  save(value) {
    this._acquire(); let prepared = null;
    try {
      const current = readObject(this.file);
      if ((current?.revision || 0) !== this.revision || (current?.epoch || 0) !== this.epoch) throw new Error('task-state-stale-writer');
      if (value.schemaVersion !== 'px.agent-task-store/2.0' || value.revision !== this.revision + 1 || (value.epoch !== this.epoch && value.epoch !== this.epoch + 1)) throw new Error('task-state-invalid-write-generation');
      const raw = Buffer.from(JSON.stringify(value), 'utf8'); if (raw.length > MAX_BYTES) throw new Error('task-state-byte-budget');
      prepared = path.join(this.directory, `.task-state-${crypto.randomUUID()}.prepared`);
      const fd = fs.openSync(prepared, 'wx');
      try { fs.writeFileSync(fd, raw); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      rejectLinks(this.file); fs.renameSync(prepared, this.file); prepared = null;
      this.revision = value.revision; this.epoch = value.epoch;
      // Windows may deny directory handles; file content was fsynced before replacement.
      let directoryFd;
      try { directoryFd = fs.openSync(this.directory, 'r'); fs.fsyncSync(directoryFd); }
      catch (error) { if (!['EPERM', 'EACCES', 'EINVAL', 'EISDIR'].includes(error.code)) throw error; }
      finally { if (directoryFd !== undefined) fs.closeSync(directoryFd); }
    } finally {
      if (prepared && fs.existsSync(prepared)) fs.unlinkSync(prepared);
      const lease = readObject(this.lock);
      if (lease?.token === this.token && lease.pid === process.pid) fs.unlinkSync(this.lock);
    }
  }
}

module.exports = { DurableTaskState };
