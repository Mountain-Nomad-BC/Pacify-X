'use strict';

(() => {
  const dimensions = Object.freeze(['configured', 'detected', 'connected', 'authoritative', 'ready']);
  function normalize(value = {}) {
    const state = Object.fromEntries(dimensions.map(key => [key, value[key] === true]));
    state.reason = typeof value.reason === 'string' ? value.reason : null;
    return Object.freeze(state);
  }
  function label(value) {
    const state = normalize(value);
    if (state.ready) return 'READY';
    if (state.authoritative) return 'AUTHORITATIVE';
    if (state.connected) return 'CONNECTED';
    if (state.detected) return 'DETECTED';
    if (state.configured) return 'CONFIGURED';
    return 'UNCONFIGURED';
  }
  function summary(value) {
    const state = normalize(value);
    return dimensions.map(key => `${key} ${state[key] ? 'yes' : 'no'}`).join(' · ');
  }
  function operational(snapshot = {}) {
    if (snapshot.connected !== true) {
      return Object.freeze({ state: 'disconnected', label: 'DISCONNECTED', tone: 'warning', connected: false });
    }
    const authoritative = normalize(snapshot.health).authoritative === true
      && snapshot.catalogSource === 'runtime.dashboard_api';
    if (!authoritative) {
      return Object.freeze({ state: 'connected-nonauthoritative', label: 'CONNECTED - NON-AUTHORITATIVE', tone: 'warning', connected: true });
    }
    if (snapshot.extensionIdentity?.matches !== true) {
      return Object.freeze({ state: 'identity-mismatch', label: 'HOST / SOURCE MISMATCH', tone: 'warning', connected: true });
    }
    return Object.freeze({ state: 'connected', label: 'CONTROL PLANE CONNECTED', tone: 'success', connected: true });
  }
  function certification(snapshot = {}) {
    const completion = snapshot.completion;
    if (!completion || typeof completion !== 'object') {
      return Object.freeze({ state: 'unavailable', label: 'CERTIFICATION UNAVAILABLE', tone: 'neutral', blockers: [] });
    }
    const blockers = Array.isArray(completion.blocking_reasons) ? completion.blocking_reasons : [];
    if (completion.certified === true && completion.certification_freshness?.fresh === true) {
      return Object.freeze({ state: 'current', label: 'CERTIFICATION CURRENT', tone: 'success', blockers });
    }
    if (completion.current_gates?.valid === false || blockers.length) {
      return Object.freeze({ state: 'stale-or-blocked', label: 'CERTIFICATION BLOCKED', tone: 'warning', blockers });
    }
    return Object.freeze({ state: 'not-certified', label: 'NOT CERTIFIED', tone: 'neutral', blockers });
  }
  function feature(snapshot = {}, id) {
    const facts = {
      projectMap: snapshot.project?.map?.valid === true,
      canonicalMemory: snapshot.memory?.retrieval_ready === true,
      coordination: snapshot.coordination?.instrumented === true,
      turbovec: snapshot.runtime?.turbovec?.active === true,
      enterpriseCatalog: Boolean(snapshot.enterprise?.catalog_id)
    };
    if (!Object.hasOwn(facts, id)) return Object.freeze({ state: 'unavailable', available: false });
    if (id === 'enterpriseCatalog' && facts[id]) return Object.freeze({ state: 'configured-offline', available: true });
    return Object.freeze({ state: facts[id] ? 'available' : 'unavailable', available: facts[id] });
  }
  globalThis.PXDashboard.define('healthState', { dimensions, normalize, label, summary, operational, certification, feature });
})();
