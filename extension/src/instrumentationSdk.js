'use strict';

const SDK_VERSION = 'px.instrumentation-sdk/1';
const EVENT_VERSION = 'px.operation-event/1';
const LIFECYCLES = new Set(['admitted', 'started', 'progress', 'waiting', 'completed', 'failed', 'cancelled', 'denied', 'unknown']);
const RESULTS = new Set(['pending', 'success', 'failure', 'cancelled', 'denied', 'unknown']);
const TIERS = new Set(['A', 'B', 'C', 'D']);

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function requiredObject(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be an object`);
  return value;
}

function buildOperationEvent(payload) {
  const event = clone(requiredObject(payload, 'payload'));
  const sdkVersion = event.sdk_version;
  delete event.sdk_version;
  if (sdkVersion !== SDK_VERSION) throw new Error(`unsupported instrumentation SDK version: ${sdkVersion}`);
  if (event.schema_version === undefined) event.schema_version = EVENT_VERSION;
  if (event.schema_version !== EVENT_VERSION) throw new Error('unsupported operation event version');
  for (const key of ['event_id', 'correlation_id']) if (typeof event[key] !== 'string' || !event[key]) throw new Error(`${key} is required`);
  const actor = requiredObject(event.actor, 'actor');
  const work = requiredObject(event.work, 'work');
  const source = requiredObject(event.source, 'source');
  const operation = requiredObject(event.operation, 'operation');
  requiredObject(event.effects, 'effects'); requiredObject(event.time, 'time'); requiredObject(event.integrity, 'integrity');
  const capture = requiredObject(event.capture, 'capture');
  if (!actor.actor_id || !actor.accountable_owner || !work.project_id || !source.route_id || !source.component) throw new Error('actor, work, and source identities are required');
  if (!TIERS.has(source.coverage_tier)) throw new Error('coverage tier is invalid');
  if (!operation.name || !LIFECYCLES.has(operation.lifecycle) || !RESULTS.has(operation.result)) throw new Error('operation lifecycle is invalid');
  if (capture.payload_included === true && capture.classification !== 'content_authorized') throw new Error('payload inclusion requires content_authorized classification');
  return event;
}

function lifecycleEvent(base, lifecycle, result) {
  const payload = clone(base); requiredObject(payload.operation, 'operation');
  payload.operation.lifecycle = lifecycle; payload.operation.result = result;
  return buildOperationEvent(payload);
}

async function instrumentOperation(base, emit, action) {
  await emit(lifecycleEvent(base, 'started', 'pending'));
  try {
    const value = await action();
    await emit(lifecycleEvent(base, 'completed', 'success'));
    return value;
  } catch (error) {
    await emit(lifecycleEvent(base, 'failed', 'failure'));
    throw error;
  }
}

module.exports = { SDK_VERSION, EVENT_VERSION, buildOperationEvent, lifecycleEvent, instrumentOperation };

