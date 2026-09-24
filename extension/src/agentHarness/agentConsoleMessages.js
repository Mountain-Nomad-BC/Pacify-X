'use strict';

const { z } = require('zod');

const MESSAGE_VERSION = 'px.agent-console.message/1.0';
const ASSET_PROTOCOL = 'px.agent-console.asset/1.0';
const MAX_BYTES = 512 * 1024;
const Id = z.string().min(1).max(160).regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/);
const Base = { schemaVersion: z.literal(MESSAGE_VERSION) };

const Inbound = z.discriminatedUnion('type', [
  z.object({ ...Base, type: z.literal('ready'), assetProtocol: z.literal(ASSET_PROTOCOL) }).strict(),
  z.object({ ...Base, type: z.literal('newTask'), goal: z.string().min(1).max(12000), mode: z.enum(['ASK','PLAN','DIAGNOSE','IMPLEMENT','REVIEW','CAMPAIGN']), workerId: z.union([Id, z.literal('auto')]), maxEffectClass: z.enum(['READ_ONLY','LOW_RISK','MUTATING','HIGH_RISK']) }).strict(),
  z.object({ ...Base, type: z.literal('sendTurn'), taskId: Id.nullable(), runId: Id.nullable(), message: z.string().min(1).max(12000), mode: z.enum(['ASK','PLAN','DIAGNOSE','IMPLEMENT','REVIEW','CAMPAIGN']), workerId: z.union([Id, z.literal('auto')]), maxEffectClass: z.enum(['READ_ONLY','LOW_RISK','MUTATING','HIGH_RISK']) }).strict(),
  z.object({ ...Base, type: z.literal('cancelRun'), runId: Id }).strict(),
  z.object({ ...Base, type: z.literal('refresh') }).strict(),
  z.object({ ...Base, type: z.literal('openControlPlane') }).strict()
]);

const Outbound = z.discriminatedUnion('type', [
  z.object({ ...Base, type: z.literal('snapshot'), assetProtocol: z.literal(ASSET_PROTOCOL), state: z.unknown() }).strict(),
  z.object({ ...Base, type: z.literal('event'), event: z.unknown() }).strict(),
  z.object({ ...Base, type: z.literal('error'), code: Id, detail: z.string().max(1000) }).strict()
]);

function bounded(schema, value, label) { const raw = JSON.stringify(value); if (Buffer.byteLength(raw, 'utf8') > MAX_BYTES) throw new Error(`${label}-too-large`); const r = schema.safeParse(value); if (!r.success) throw new Error(`${label}-invalid:${r.error.issues.slice(0,4).map(i => `${i.path.join('.')}:${i.code}`).join(',')}`); return r.data; }
function validateInbound(value) { return bounded(Inbound, value, 'agent-console-inbound'); }
function validateOutbound(value) { return bounded(Outbound, value, 'agent-console-outbound'); }

module.exports = { MESSAGE_VERSION, ASSET_PROTOCOL, validateInbound, validateOutbound };
