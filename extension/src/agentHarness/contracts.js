'use strict';

const { z } = require('zod');

const Id = z.string().min(1).max(160).regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/);
const Iso = z.string().datetime();
const Json = z.unknown();
const EffectClass = z.enum(['READ_ONLY', 'LOW_RISK', 'MUTATING', 'HIGH_RISK']);
const CostClass = z.enum(['local', 'free-quota', 'subscription', 'billable-api', 'enterprise-budget', 'unknown']);
const TaskMode = z.enum(['ASK', 'PLAN', 'DIAGNOSE', 'IMPLEMENT', 'REVIEW', 'CAMPAIGN']);
const TaskStage = z.enum(['INTAKE', 'CLASSIFY', 'PLAN', 'RETRIEVE', 'DIAGNOSE', 'IMPLEMENT', 'REVIEW', 'VERIFY', 'RECOVER', 'COMPLETE', 'FAILED', 'CANCELLED']);

const CompletionRequirement = z.object({
  id: Id,
  required: z.boolean().default(true),
  label: z.string().min(1).max(240),
  evidenceTypes: z.array(Id).max(24).default([])
}).strict();

const PxTask = z.object({
  schemaVersion: z.literal('px.agent-task/1.0'),
  taskId: Id,
  createdAt: Iso,
  updatedAt: Iso,
  goal: z.string().min(1).max(12000),
  mode: TaskMode,
  stage: TaskStage,
  targets: z.array(z.string().max(1024)).max(80).default([]),
  activeSkills: z.array(Id).max(80).default([]),
  constraints: z.object({
    maxEffectClass: EffectClass.default('READ_ONLY'),
    contextBudgetTokens: z.number().int().positive().max(2_000_000),
    taskCostCeilingUsd: z.number().nonnegative().max(1_000_000).nullable(),
    localFirst: z.boolean(),
    requireApprovalBeforeBillable: z.boolean()
  }).strict(),
  completionContract: z.array(CompletionRequirement).max(80),
  confidence: z.number().min(0).max(1).nullable(),
  status: z.enum(['active', 'blocked', 'complete', 'failed', 'cancelled'])
}).strict();

const PxRun = z.object({
  schemaVersion: z.literal('px.agent-run/1.0'),
  runId: Id,
  taskId: Id,
  createdAt: Iso,
  updatedAt: Iso,
  status: z.enum(['running', 'waiting', 'blocked', 'complete', 'failed', 'cancelled']),
  activeWorkerId: Id.nullable(),
  providerSessionRef: z.string().max(512).nullable(),
  routeHistory: z.array(z.object({ workerId: Id, selectedAt: Iso, reason: z.string().max(500) }).strict()).max(100),
  round: z.number().int().nonnegative(),
  lastError: z.string().max(1000).nullable()
}).strict();

const LibrarianArtifact = z.object({
  schemaVersion: z.literal('px.librarian-artifact/1.0'),
  intent: Id,
  stage: TaskStage,
  domains: z.array(Id).max(24),
  skillCandidates: z.array(Id).max(40),
  retrievalRequired: z.boolean(),
  retrievalQueries: z.array(z.string().max(500)).max(20),
  routeRecommendation: Id.nullable(),
  escalationRecommended: z.boolean(),
  confidence: z.number().min(0).max(1),
  durationMs: z.number().nonnegative(),
  source: z.enum(['tiny-model', 'deterministic-fallback'])
}).strict();

const ContextRef = z.object({
  refId: Id,
  kind: Id,
  label: z.string().min(1).max(500),
  source: z.string().max(500).nullable(),
  tokenEstimate: z.number().int().nonnegative(),
  authority: z.string().max(120).nullable(),
  freshAt: Iso.nullable(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  content: z.string().max(200000).nullable()
}).strict();

const ContextPack = z.object({
  schemaVersion: z.literal('px.context-pack/1.0'),
  contextId: Id,
  taskId: Id,
  createdAt: Iso,
  budgetTokens: z.number().int().positive(),
  suppliedTokens: z.number().int().nonnegative(),
  consideredCount: z.number().int().nonnegative(),
  selectedCount: z.number().int().nonnegative(),
  refs: z.array(ContextRef).max(120),
  instruction: z.string().max(30000)
}).strict();

const WorkerDescriptor = z.object({
  workerId: Id,
  adapterId: Id,
  providerId: Id,
  modelId: z.string().min(1).max(240),
  displayName: z.string().min(1).max(240),
  costClass: CostClass,
  contextLimit: z.number().int().positive().nullable(),
  locality: z.enum(['local', 'remote', 'hybrid']),
  capabilities: z.object({
    coding: z.number().min(0).max(1).default(0),
    planning: z.number().min(0).max(1).default(0),
    review: z.number().min(0).max(1).default(0),
    classification: z.number().min(0).max(1).default(0),
    toolUse: z.boolean().default(false),
    vision: z.boolean().default(false),
    structuredOutput: z.boolean().default(false)
  }).strict(),
  supportedEffectClass: EffectClass,
  enabled: z.boolean(),
  reliability: z.number().min(0).max(1),
  latencyClass: z.enum(['fast', 'medium', 'slow', 'unknown'])
}).strict();

const UsageReceipt = z.object({
  schemaVersion: z.literal('px.usage-receipt/1.0'),
  workerId: Id,
  providerId: Id,
  costClass: CostClass,
  inputTokens: z.number().int().nonnegative().nullable(),
  outputTokens: z.number().int().nonnegative().nullable(),
  totalTokens: z.number().int().nonnegative().nullable(),
  actualChargeUsd: z.number().nonnegative().nullable(),
  projectedChargeUsd: z.number().nonnegative().nullable(),
  billingIdentityKnown: z.boolean(),
  quotaRemaining: z.number().nonnegative().nullable(),
  capturedAt: Iso
}).strict();

const Evidence = z.object({
  evidenceId: Id,
  taskId: Id,
  runId: Id,
  type: Id,
  status: z.enum(['pass', 'fail', 'info']),
  summary: z.string().min(1).max(1000),
  sourceRef: z.string().max(1000).nullable(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  capturedAt: Iso
}).strict();

const PxEvent = z.object({
  schemaVersion: z.literal('px.agent-event/1.0'),
  eventId: Id,
  sequence: z.number().int().nonnegative(),
  type: Id,
  emittedAt: Iso,
  taskId: Id.nullable(),
  runId: Id.nullable(),
  turnId: Id.nullable(),
  roundId: Id.nullable(),
  actor: Id,
  workerId: Id.nullable(),
  parentEventId: Id.nullable(),
  status: z.enum(['started', 'progress', 'succeeded', 'failed', 'blocked', 'cancelled', 'info']),
  summary: z.string().max(1000),
  payload: z.record(z.string(), Json).default({})
}).strict();

const PxToolRequest = z.object({
  requestId: Id,
  taskId: Id,
  runId: Id,
  workerId: Id,
  toolId: Id,
  effectClass: EffectClass,
  arguments: z.record(z.string(), Json),
  scopeRefs: z.array(z.string().max(1000)).max(80),
  requestedAt: Iso
}).strict();

const PxToolResult = z.object({
  requestId: Id,
  toolId: Id,
  status: z.enum(['succeeded', 'failed', 'blocked', 'cancelled']),
  summary: z.string().max(1000),
  output: Json.nullable(),
  evidence: z.array(Evidence).max(40),
  completedAt: Iso
}).strict();

function parse(schema, value, label) {
  const result = schema.safeParse(value);
  if (!result.success) throw new Error(`${label}-invalid:${result.error.issues.slice(0, 6).map(i => `${i.path.join('.')}:${i.code}`).join(',')}`);
  return result.data;
}

module.exports = {
  Id, Iso, EffectClass, CostClass, TaskMode, TaskStage, CompletionRequirement,
  PxTask, PxRun, LibrarianArtifact, ContextRef, ContextPack, WorkerDescriptor,
  UsageReceipt, Evidence, PxEvent, PxToolRequest, PxToolResult, parse
};
