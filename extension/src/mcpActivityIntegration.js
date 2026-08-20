'use strict';

const crypto = require('crypto');
const { SDK_VERSION, buildOperationEvent } = require('./instrumentationSdk');

function sha(value) {
  return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
}

function cleanId(value, fallback) {
  const result = String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 160);
  return result || fallback;
}

function actorAttestation(input = {}, context = {}, processId = process.pid) {
  const required = ['actor_id', 'session_id', 'harness', 'accountable_owner'];
  const missing = required.filter(field => typeof input[field] !== 'string' || !input[field].trim());
  const coreIdentityPresent = ['actor_id', 'session_id', 'harness'].every(field => typeof input[field] === 'string' && input[field].trim());
  const contextualSession = context?.source?.session_id;
  return {
    actor: {
      actorId: cleanId(input.actor_id, 'mcp-client'),
      sessionId: cleanId(input.session_id || contextualSession, `mcp-server-${processId}`),
      harness: String(input.harness || context?.source?.surface || 'MCP client').slice(0, 120),
      accountableOwner: String(input.accountable_owner || 'unattested-owner').slice(0, 160)
    },
    actorKind: coreIdentityPresent ? 'agent' : 'unknown',
    identityAttestation: coreIdentityPresent ? 'self_asserted' : 'unattested',
    unattestedFields: missing
  };
}

function createMcpActivityIntegration(options) {
  const state = {
    schema_version: 'px.mcp-instrumentation-health/1.0', registered_tools: [], calls: 0,
    emitted_events: 0, dropped_events: 0, last_drop_type: null,
    identity: { self_asserted_calls: 0, unattested_calls: 0 }
  };
  const now = options.now || (() => new Date().toISOString());
  const uuid = options.uuid || (() => crypto.randomUUID());

  function health() {
    return {
      ...state,
      registered_tools: [...state.registered_tools],
      status: state.dropped_events ? 'degraded' : 'healthy',
      authority_granted: false,
      canonical_bus_connected: false,
      coverage_tier: 'C',
      limitations: ['Events are canonical-contract attestations retained in the project activity ledger; direct canonical-bus publication remains an O11 reconciliation dependency.']
    };
  }

  function canonicalEvent(name, definition, input, lifecycle, result, correlationId, attestation, startedAt, durationMs) {
    const readOnly = Boolean(definition.annotations?.readOnlyHint);
    const reportedCorrelation = typeof input?.correlation_id === 'string' && input.correlation_id ? cleanId(input.correlation_id, null) : null;
    return buildOperationEvent({
      sdk_version: SDK_VERSION,
      event_id: `mcp-${uuid()}-${lifecycle}`,
      correlation_id: correlationId,
      parent_correlation_id: reportedCorrelation,
      actor: {
        actor_id: attestation.actor.actorId,
        actor_kind: attestation.actorKind,
        session_id: attestation.actor.sessionId,
        harness: attestation.actor.harness,
        accountable_owner: attestation.actor.accountableOwner
      },
      work: {
        project_id: cleanId(options.projectId?.() || 'unresolved-project', 'unresolved-project'),
        task_id: input?.task_id ? cleanId(input.task_id, null) : null,
        claim_id: input?.claim_id ? cleanId(input.claim_id, null) : null,
        orchestration_id: input?.orchestration_id ? cleanId(input.orchestration_id, null) : null
      },
      source: { route_id: 'mcp.tool', component: 'src/mcpActivityIntegration.js', host_id: null, coverage_tier: 'C' },
      operation: { name, lifecycle, result },
      effects: {
        declared: readOnly ? ['read'] : ['write'],
        observed: readOnly ? ['read'] : ['write'],
        scope_refs: [`tool:${cleanId(name, 'unknown')}`]
      },
      provider: null,
      time: { observed_at: now(), started_at: startedAt, duration_ms: durationMs, freshness: 'live' },
      integrity: { input_sha256: null, output_sha256: null, previous_event_sha256: null },
      capture: { classification: 'metadata_only', payload_included: false }
    });
  }

  function emit(name, definition, input, lifecycle, result, correlationId, attestation, startedAt, durationMs) {
    if (options.policy().captureMcpCalls === false) return { recorded: false, reason: 'mcp-capture-disabled' };
    const event = canonicalEvent(name, definition, input, lifecycle, result, correlationId, attestation, startedAt, durationMs);
    const legacyStatus = { started: 'started', completed: 'succeeded', failed: 'failed' }[lifecycle] || 'observed';
    try {
      const recorded = options.recordActivity(
        options.workspaceRoot(),
        attestation.actor,
        {
          category: 'mcp', operation: name, status: legacyStatus, source: 'pacify-x-mcp',
          effect: definition.annotations?.readOnlyHint ? 'workspace-read' : 'workspace-write',
          correlationId, parentCorrelationId: event.parent_correlation_id,
          taskId: input?.task_id, claimId: input?.claim_id, durationMs,
          metadata: {
            tool: name,
            declared_read_only: Boolean(definition.annotations?.readOnlyHint),
            argument_keys: Object.keys(input || {}).sort(),
            identity_attestation: attestation.identityAttestation,
            unattested_fields: attestation.unattestedFields,
            reported_correlation_id: event.parent_correlation_id,
            canonical_schema_version: event.schema_version,
            canonical_sdk_version: SDK_VERSION,
            canonical_event_sha256: sha(event),
            payload_retained: false
          }
        },
        options.policy()
      );
      if (recorded?.recorded === false) throw new Error(`activity-${recorded.reason || 'not-recorded'}`);
      state.emitted_events += 1;
      return recorded;
    } catch (error) {
      state.dropped_events += 1;
      state.last_drop_type = error?.constructor?.name || 'Error';
      options.onDrop?.({ type: state.last_drop_type, tool: name, lifecycle });
      return { recorded: false, reason: 'instrumentation-drop', failure_type: state.last_drop_type };
    }
  }

  function wrapTool(name, definition, handler) {
    if (!name || typeof handler !== 'function') throw new Error('MCP tool identity and handler are required');
    if (state.registered_tools.includes(name)) throw new Error(`duplicate MCP tool instrumentation: ${name}`);
    state.registered_tools.push(name);
    return async input => {
      const context = options.contextEnvelope?.() || {};
      const attestation = actorAttestation(input, context, options.processId);
      state.calls += 1;
      state.identity[`${attestation.identityAttestation}_calls`] += 1;
      const correlationId = `mcp-${uuid()}`;
      const startedMs = Date.now();
      const startedAt = now();
      emit(name, definition, input, 'started', 'pending', correlationId, attestation, startedAt, 0);
      try {
        const value = await handler(input);
        emit(name, definition, input, 'completed', 'success', correlationId, attestation, startedAt, Date.now() - startedMs);
        return value;
      } catch (error) {
        emit(name, definition, input, 'failed', 'failure', correlationId, attestation, startedAt, Date.now() - startedMs);
        throw error;
      }
    };
  }

  return { wrapTool, health, actorAttestation: (input, context) => actorAttestation(input, context, options.processId) };
}

module.exports = { actorAttestation, createMcpActivityIntegration };
