'use strict';

const { z } = require('zod');

const MESSAGE_SCHEMA_VERSION = 'px.sidebar.message/1.1';
const SIDEBAR_ASSET_PROTOCOL = 'px.sidebar.asset/1.2';
const MAX_MESSAGE_BYTES = 256 * 1024;
const ID = z.string().min(1).max(160).regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/);
const EntityType = z.enum(['plan', 'wave', 'task', 'agent', 'orchestration', 'provider', 'attention']);
const Base = { schemaVersion: z.literal(MESSAGE_SCHEMA_VERSION) };

const InboundSidebarMessage = z.discriminatedUnion('type', [
  z.object({ ...Base, type: z.literal('ready'), assetProtocol: z.literal(SIDEBAR_ASSET_PROTOCOL) }).strict(),
  z.object({
    ...Base, type: z.literal('rendered'), assetProtocol: z.literal(SIDEBAR_ASSET_PROTOCOL), revision: z.number().int().nonnegative(), visibleComponentCount: z.number().int().min(3).max(11),
    waveCount: z.number().int().nonnegative().max(12), taskCount: z.number().int().nonnegative().max(80), agentCount: z.number().int().nonnegative().max(12),
    orchestrationCount: z.number().int().nonnegative().max(8), recentCount: z.number().int().nonnegative().max(5), attentionCount: z.number().int().nonnegative().max(12),
    providerCount: z.number().int().nonnegative().max(12), connected: z.boolean()
  }).strict(),
  z.object({ ...Base, type: z.literal('openControlPlane') }).strict(),
  z.object({ ...Base, type: z.literal('openEntity'), entityType: EntityType, entityId: ID }).strict(),
  z.object({ ...Base, type: z.literal('toggleWave'), waveId: ID, expanded: z.boolean() }).strict(),
  z.object({ ...Base, type: z.literal('toggleTask'), taskId: ID, expanded: z.boolean() }).strict(),
  z.object({ ...Base, type: z.literal('selectProvider'), providerId: ID.nullable() }).strict(),
  z.object({ ...Base, type: z.literal('providerPrevious') }).strict(),
  z.object({ ...Base, type: z.literal('providerNext') }).strict(),
  z.object({ ...Base, type: z.literal('retryConnection') }).strict(),
  z.object({ ...Base, type: z.literal('openPlanFromPunch'), planId: ID }).strict()
]);

const Subsystem = z.object({ id: ID, label: z.string().max(80), state: z.enum(['healthy', 'degraded', 'unavailable', 'unconfigured']) }).strict();
const Task = z.object({ id: ID, name: z.string().max(300), status: z.enum(['complete', 'active', 'verifying', 'blocked', 'failed', 'queued', 'cancelled', 'skipped']), weight: z.number().positive().max(1_000_000), progressPercent: z.number().min(0).max(100).nullable(), claimId: ID.nullable(), updatedAt: z.string().datetime().nullable(), subtasks: z.array(z.object({ id: ID, name: z.string().max(300), status: z.string().max(24), progressPercent: z.number().min(0).max(100).nullable() }).strict()).max(12) }).strict();
const Provider = z.object({
  providerId: ID, providerName: z.string().max(240), providerClass: z.enum(['billable-api', 'subscription', 'enterprise-budget', 'local', 'unknown']),
  connectionState: z.string().max(24), activityState: z.string().max(24), billingEnabled: z.boolean().nullable(), fallbackEnabled: z.boolean().nullable(), fallbackActive: z.boolean(),
  currentTaskId: ID.nullable(), currentTaskName: z.string().max(240).nullable(), currentAgentName: z.string().max(160).nullable(),
  spendCurrent: z.number().nullable(), budgetLimit: z.number().nullable(), budgetRemaining: z.number().nullable(), budgetPercent: z.number().nullable(),
  tokenTotal: z.number().nullable(), tokenBudget: z.number().nullable(), requestCount: z.number().nullable(), ratePerMinute: z.number().nullable(),
  currency: z.string().max(8).nullable(), telemetrySource: z.string().max(120), telemetryFreshAt: z.string().datetime().nullable(), stale: z.boolean()
}).strict();

const SidebarProjection = z.object({
  schemaVersion: z.literal('px.sidebar.snapshot/1.0'), revision: z.number().int().nonnegative(), generatedAt: z.string().datetime(),
  status: z.object({ state: z.enum(['connected', 'degraded', 'recovering', 'blocked', 'disconnected', 'unconfigured']), label: z.string().max(40), connected: z.boolean(), version: z.string().max(40), revision: z.number().int().nonnegative(), reason: z.string().max(500).nullable(), lastConnectedAt: z.string().datetime().nullable(), subsystems: z.array(Subsystem).max(8) }).strict(),
  execution: z.object({ planId: ID, planName: z.string().max(300), currentWaveId: ID.nullable(), currentWaveName: z.string().max(300).nullable(), completedTasks: z.number().int().nonnegative(), totalEligibleTasks: z.number().int().nonnegative(), activeTasks: z.number().int().nonnegative(), blockedTasks: z.number().int().nonnegative(), queuedTasks: z.number().int().nonnegative(), verifyingTasks: z.number().int().nonnegative(), progressPercent: z.number().min(0).max(100).nullable(), activeAgentCount: z.number().int().nonnegative(), activeOrchestrationCount: z.number().int().nonnegative(), stateRevision: z.number().int().nonnegative(), lastUpdatedAt: z.string().datetime() }).strict().nullable(),
  lastRun: z.object({ planId: ID, planName: z.string().max(300), completedAt: z.string().datetime().nullable(), completedTasks: z.number().int().nonnegative(), totalTasks: z.number().int().nonnegative() }).strict().nullable(),
  waves: z.array(z.object({ id: ID, name: z.string().max(300), index: z.number().int().positive(), status: z.string().max(24), progressPercent: z.number().min(0).max(100).nullable(), tasks: z.array(Task).max(80) }).strict()).max(12),
  punch: z.object({ complete: z.number().int().nonnegative(), active: z.number().int().nonnegative(), queued: z.number().int().nonnegative(), blocked: z.number().int().nonnegative(), verifying: z.number().int().nonnegative(), excluded: z.number().int().nonnegative(), total: z.number().int().nonnegative() }).strict(),
  agents: z.array(z.object({ agentId: ID, displayName: z.string().max(240), type: z.string().max(80), host: z.string().max(120).nullable(), ide: z.string().max(120).nullable(), taskId: ID.nullable(), taskName: z.string().max(240).nullable(), claimId: ID.nullable(), orchestrationId: ID.nullable(), state: z.enum(['active', 'waiting', 'verifying', 'blocked', 'recovering', 'stale']), progressPercent: z.number().min(0).max(100).nullable(), lastHeartbeatAt: z.string().datetime().nullable(), heartbeatAgeMs: z.number().int().nonnegative().nullable() }).strict()).max(12),
  orchestrations: z.array(z.object({ id: ID, name: z.string().max(240), state: z.string().max(24), updatedAt: z.string().datetime().nullable() }).strict()).max(8),
  recent: z.array(z.object({ id: ID, kind: ID, label: z.string().max(240), state: z.string().max(24), occurredAt: z.string().datetime().nullable(), entityType: EntityType.nullable(), entityId: ID.nullable() }).strict()).max(5),
  attention: z.array(z.object({ id: ID, severity: z.enum(['info', 'warning', 'error', 'critical']), title: z.string().max(240), detail: z.string().max(500).nullable(), entityType: EntityType.nullable(), entityId: ID.nullable() }).strict()).max(12),
  providerState: z.object({ providers: z.array(Provider).max(12), configuredCount: z.number().int().nonnegative(), telemetryAvailable: z.boolean(), activeCount: z.number().int().nonnegative() }).strict(),
  ui: z.object({ expandedWaveIds: z.array(ID).max(40), expandedTaskIds: z.array(ID).max(80), selectedProviderId: ID.nullable() }).strict(),
  performance: z.object({ projectionMs: z.number().nonnegative(), source: z.literal('single-bounded-host-snapshot'), workspaceScan: z.literal(false) }).strict()
}).strict();

const OutboundSidebarMessage = z.discriminatedUnion('type', [
  z.object({
    ...Base, type: z.literal('snapshot'),
    capabilities: z.object({ renderAcknowledgement: z.literal(true), assetProtocol: z.literal(SIDEBAR_ASSET_PROTOCOL) }).strict(),
    projection: SidebarProjection
  }).strict(),
  z.object({ ...Base, type: z.literal('error'), code: ID, detail: z.string().max(500) }).strict()
]);

function parseBounded(schema, input, label) {
  let serialized;
  try { serialized = JSON.stringify(input); } catch { throw new Error(`${label}-not-serializable`); }
  if (Buffer.byteLength(serialized, 'utf8') > MAX_MESSAGE_BYTES) throw new Error(`${label}-too-large`);
  const result = schema.safeParse(input);
  if (!result.success) throw new Error(`${label}-invalid:${result.error.issues.slice(0, 4).map(issue => `${issue.path.join('.')}:${issue.code}`).join(',')}`);
  return result.data;
}

function validateSidebarInbound(input) { return parseBounded(InboundSidebarMessage, input, 'sidebar-inbound-message'); }
function validateSidebarOutbound(input) { return parseBounded(OutboundSidebarMessage, input, 'sidebar-outbound-message'); }

function diagnosticToken(value, fallback) {
  if (typeof value !== 'string' || !value) return fallback;
  const bounded = value.slice(0, 80);
  return /^[A-Za-z0-9._:/-]+$/.test(bounded) ? bounded : 'invalid';
}

function describeSidebarInboundRejection(input, error) {
  const record = input && typeof input === 'object' && !Array.isArray(input) ? input : null;
  let keys = [];
  try { keys = record ? Object.keys(record).sort().slice(0, 16).map(key => diagnosticToken(key, 'invalid')) : []; } catch { keys = ['unavailable']; }
  const observedSchema = diagnosticToken(record?.schemaVersion, 'missing'); const observedType = diagnosticToken(record?.type, 'missing'); const observedAsset = diagnosticToken(record?.assetProtocol, 'missing');
  const admittedTypes = new Set(['ready', 'rendered', 'openControlPlane', 'openEntity', 'toggleWave', 'toggleTask', 'selectProvider', 'providerPrevious', 'providerNext', 'retryConnection', 'openPlanFromPunch']);
  const classification = observedSchema !== MESSAGE_SCHEMA_VERSION ? 'stale-or-unsupported-message-schema' : !admittedTypes.has(observedType) ? 'unsupported-message-type' : ['ready', 'rendered'].includes(observedType) && observedAsset !== SIDEBAR_ASSET_PROTOCOL ? 'stale-or-unsupported-asset-protocol' : 'message-shape-invalid';
  const validation = diagnosticToken(String(error?.message || error || 'rejected').split(':').at(-1), 'rejected');
  return `sidebar-inbound-rejected:code=${classification};expectedSchema=${MESSAGE_SCHEMA_VERSION};observedSchema=${observedSchema};expectedAsset=${SIDEBAR_ASSET_PROTOCOL};observedAsset=${observedAsset};observedType=${observedType};validation=${validation};keys=${keys.join('|') || 'none'}`.slice(0, 500);
}

module.exports = { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL, SidebarProjection, validateSidebarInbound, validateSidebarOutbound, describeSidebarInboundRejection };
