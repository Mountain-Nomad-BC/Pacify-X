'use strict';

const crypto = require('node:crypto');

const DEFAULT_DEPENDENCIES = Object.freeze({
  skills: ['capabilities', 'workflows'],
  capabilities: ['workflows', 'agents'],
  workflows: ['agents'],
  providers: ['models', 'routes', 'costs'],
  models: ['routes', 'costs'],
  repositories: ['git', 'environment', 'dashboard'],
  git: ['dashboard'],
  environment: ['tools', 'packages', 'dashboard'],
  policies: ['routes', 'costs', 'validation'],
  coordination: ['dashboard'],
  validation: ['dashboard']
});

class RevisionStore {
  constructor({ dependencies = DEFAULT_DEPENDENCIES, now = Date.now } = {}) {
    this.dependencies = new Map(Object.entries(dependencies).map(([key, values]) => [key, [...values]]));
    this.revisions = new Map();
    this.invalidations = [];
    this.now = now;
  }

  invalidate(domain, reason = 'unspecified') {
    const affected = [];
    const pending = [String(domain)];
    const seen = new Set();
    while (pending.length) {
      const current = pending.shift();
      if (!current || seen.has(current)) continue;
      seen.add(current); affected.push(current);
      this.revisions.set(current, (this.revisions.get(current) || 0) + 1);
      pending.push(...(this.dependencies.get(current) || []));
    }
    this.invalidations.push({ domain: String(domain), reason: String(reason).slice(0, 160), affected, at: this.now() });
    if (this.invalidations.length > 100) this.invalidations.shift();
    return affected;
  }

  revision(domain) { return this.revisions.get(String(domain)) || 0; }

  fingerprint(domains) {
    const state = [...new Set(domains.map(String))].sort().map(domain => [domain, this.revision(domain)]);
    return crypto.createHash('sha256').update(JSON.stringify(state)).digest('hex');
  }

  snapshot() {
    return {
      schema_version: 'px.dependency-revisions/1.0',
      revisions: Object.fromEntries([...this.revisions].sort(([a], [b]) => a.localeCompare(b))),
      stale_domains: [...new Set(this.invalidations.flatMap(item => item.affected))].sort(),
      recent_invalidations: this.invalidations.slice(-20)
    };
  }
}

class MetadataCache {
  constructor({ store = null, namespace = 'pacifyX.metadata-cache/1.0', now = Date.now, maximumEntries = 64 } = {}) {
    this.store = store; this.namespace = namespace; this.now = now; this.maximumEntries = maximumEntries;
    this.memory = new Map();
    this.metrics = { hits: 0, misses: 0, staleHits: 0, writes: 0, invalidations: 0, persistentRestores: 0, corruptions: 0 };
  }

  _key(key) { return `${this.namespace}:${crypto.createHash('sha256').update(String(key)).digest('hex')}`; }

  async get(key, { fingerprint, allowStale = false, maxAgeMs = Infinity } = {}) {
    const storageKey = this._key(key);
    let record = this.memory.get(storageKey);
    if (!record && this.store?.get) {
      try { record = await this.store.get(storageKey); } catch { record = null; }
      if (record) { this.memory.set(storageKey, record); this.metrics.persistentRestores += 1; }
    }
    if (!record || record.schema_version !== 'px.metadata-cache-record/1.0' || typeof record.value !== 'object') {
      if (record) this.metrics.corruptions += 1;
      this.metrics.misses += 1; return null;
    }
    const ageMs = Math.max(0, this.now() - Number(record.created_at_ms || 0));
    const current = (!fingerprint || record.source_fingerprint === fingerprint) && ageMs <= maxAgeMs;
    if (!current && !allowStale) { this.metrics.misses += 1; return null; }
    this.metrics[current ? 'hits' : 'staleHits'] += 1;
    return { ...record, age_ms: ageMs, stale: !current };
  }

  async set(key, value, { fingerprint, dependencyFingerprints = {}, freshnessClass = 'stable', invalidationReason = 'refresh' } = {}) {
    const storageKey = this._key(key);
    const record = {
      schema_version: 'px.metadata-cache-record/1.0', producer_version: require('../package.json').version,
      source_fingerprint: fingerprint || null, dependency_fingerprints: dependencyFingerprints,
      created_at_ms: this.now(), last_validated_at_ms: this.now(), freshness_class: freshnessClass,
      invalidation_reason: String(invalidationReason).slice(0, 160), value
    };
    this.memory.set(storageKey, record);
    while (this.memory.size > this.maximumEntries) this.memory.delete(this.memory.keys().next().value);
    if (this.store?.update) await this.store.update(storageKey, record);
    this.metrics.writes += 1; return record;
  }

  invalidate(key) { this.memory.delete(this._key(key)); this.metrics.invalidations += 1; }
  snapshot() { return { schema_version: 'px.metadata-cache/1.0', entries: this.memory.size, maximum_entries: this.maximumEntries, metrics: { ...this.metrics } }; }
}

module.exports = { RevisionStore, MetadataCache, DEFAULT_DEPENDENCIES };
