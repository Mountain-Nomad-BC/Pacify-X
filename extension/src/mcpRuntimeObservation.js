'use strict';

const DEFAULT_FRESHNESS_MS = 24 * 60 * 60 * 1000;

function observeMcpRuntime(registration, activity, serverVersion, options = {}) {
  const base = { ...(registration || {}) };
  if (base.registered !== true) return { ...base, runtime_verified: false };
  if (activity?.integrity?.valid !== true) return {
    ...base, status: 'registered_unverified', runtime_verified: false,
    detail: 'Definition provider registered; the project activity ledger is unavailable or invalid.'
  };
  const nowMs = Number(options.nowMs ?? Date.now());
  const freshnessMs = Number(options.freshnessMs ?? DEFAULT_FRESHNESS_MS);
  const version = String(serverVersion || '');
  const event = (activity.events || []).find(item => {
    const observedMs = Date.parse(item?.timestamp || '');
    return item?.category === 'mcp'
      && item?.source === 'pacify-x-mcp'
      && item?.status === 'succeeded'
      && item?.metadata?.server_version === version
      && Number.isFinite(observedMs)
      && nowMs >= observedMs
      && nowMs - observedMs <= freshnessMs;
  });
  if (!event) return {
    ...base, status: 'registered_unverified', runtime_verified: false,
    detail: 'Definition provider registered; no fresh successful invocation from this exact bundled server version is retained.'
  };
  return {
    ...base,
    status: 'runtime_verified',
    runtime_verified: true,
    detail: `Successful ${event.operation} invocation retained in the integrity-valid project activity ledger.`,
    verified_at: event.timestamp,
    verified_operation: event.operation,
    evidence_event_id: event.event_id
  };
}

module.exports = { DEFAULT_FRESHNESS_MS, observeMcpRuntime };
