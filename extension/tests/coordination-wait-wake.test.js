'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  createParallelPlan, claimTask, recordProgress, registerWait, waitStatus, acknowledgeWake,
  sendMessage, readMessages, consumeMessage, readCoordination, releaseTask
} = require('../src/coordinationManager');

function root() { return fs.mkdtempSync(path.join(os.tmpdir(), 'px-coord-wait-')); }
function actor(id, session = `${id}-session`) { return { actorId: id, sessionId: session, harness: 'test', accountableOwner: 'test' }; }
function proof(claim) { return { claim_id: claim.id, fencing_tokens: claim.fencing_tokens }; }
function plan(workspace, tasks) { return createParallelPlan(workspace, actor('planner'), { objective: 'test wait/wake', tasks }); }

function task(id, claim, extra = {}) {
  return { id, title: id, claims: [claim], acceptance: ['done'], ...extra };
}

test('durable task wait wakes idempotently and returns a resume packet without granting a claim', () => {
  const workspace = root();
  try {
    plan(workspace, [task('producer', 'a.txt'), task('consumer', 'b.txt')]);
    const producer = claimTask(workspace, actor('producer'), { task_id: 'producer' }).result.receipt;
    const consumer = claimTask(workspace, actor('consumer'), { task_id: 'consumer' }).result.receipt;
    const wait = registerWait(workspace, actor('consumer'), {
      task_id: 'consumer', checkpoint_id: 'ctx-123', condition_type: 'task', dependency_ids: ['producer'],
      exact_next_action: 'hydrate producer result', cognitive_generation_id: 'cg-7', ...proof({ id: consumer.claim_id, fencing_tokens: consumer.fencing_tokens })
    }).result.receipt;
    assert.equal(wait.status, 'waiting');
    recordProgress(workspace, actor('producer'), {
      task_id: 'producer', status: 'completed', summary: 'done', evidence: ['ev-1'],
      ...proof({ id: producer.claim_id, fencing_tokens: producer.fencing_tokens })
    });
    const status = waitStatus(workspace, wait.wait_id);
    assert.equal(status.wait.status, 'satisfied');
    assert.equal(status.wakes.length, 1);
    assert.equal(status.resume_packet.checkpoint_id, 'ctx-123');
    assert.equal(status.resume_packet.exact_next_action, 'hydrate producer result');
    assert.equal(status.resume_packet.fresh_claim_required, false);
    assert.equal(status.resume_packet.cognitive_generation_id, 'cg-7');

    const ack = acknowledgeWake(workspace, actor('consumer'), { wake_id: status.wakes[0].wake_id });
    assert.equal(ack.result.receipt.fresh_claim_required, false);
    const again = acknowledgeWake(workspace, actor('consumer'), { wake_id: status.wakes[0].wake_id });
    assert.equal(again.result.receipt.idempotent, true);
    assert.equal(waitStatus(workspace, wait.wait_id).wakes.length, 1);
  } finally { fs.rmSync(workspace, { recursive: true, force: true }); }
});

test('wait registration rejects a dependency cycle and requires exact current fencing proof', () => {
  const workspace = root();
  try {
    plan(workspace, [task('one', 'a.txt'), task('two', 'b.txt', { depends_on: ['one'] })]);
    const one = claimTask(workspace, actor('one'), { task_id: 'one' }).result.receipt;
    assert.throws(() => registerWait(workspace, actor('one'), {
      task_id: 'one', checkpoint_id: 'ctx-cycle', condition_type: 'task', dependency_ids: ['two'],
      ...proof({ id: one.claim_id, fencing_tokens: one.fencing_tokens })
    }), /coordination-wait-cycle/);
    assert.throws(() => registerWait(workspace, actor('one'), {
      task_id: 'one', checkpoint_id: 'ctx-bad', condition_type: 'message', dependency_ids: ['msg-x'], claim_id: one.claim_id,
      fencing_tokens: Object.fromEntries(Object.entries(one.fencing_tokens).map(([key, value]) => [key, value + 1]))
    }), /stale-fencing-token/);
  } finally { fs.rmSync(workspace, { recursive: true, force: true }); }
});

test('private mailbox payload cannot cross remote/browser transport without explicit egress approval', () => {
  const workspace = root();
  try {
    plan(workspace, [task('receiver-task', 'private.txt')]);
    const claimed = claimTask(workspace, actor('receiver'), { task_id: 'receiver-task' }).result.receipt;
    const wait = registerWait(workspace, actor('receiver'), {
      task_id: 'receiver-task', checkpoint_id: 'private-checkpoint', condition_type: 'message', dependency_ids: ['msg-fixed'],
      ...proof({ id: claimed.claim_id, fencing_tokens: claimed.fencing_tokens })
    }).result.receipt;
    assert.throws(() => sendMessage(workspace, actor('sender'), {
      recipient_id: 'receiver', recipient_transport: 'browser', privacy_class: 'private', payload: 'private detail'
    }), /private-message-egress-denied/);
    const sent = sendMessage(workspace, actor('sender'), {
      recipient_id: 'receiver', recipient_transport: 'local', privacy_class: 'private', payload: 'private detail', message_id: 'msg-fixed', evidence_refs: ['secret-ref']
    });
    assert.equal(sent.result.receipt.message_id, 'msg-fixed');
    assert.match(sent.private_delivery_token, /^[A-Za-z0-9_-]{43}$/);
    assert.equal(JSON.stringify(sent.event).includes(sent.private_delivery_token), false);
    assert.equal(readMessages(workspace, actor('receiver'), { recipient_id: 'receiver' }).messages.length, 0);
    assert.equal(readMessages(workspace, actor('other'), { recipient_id: 'receiver' }, { includePrivate: true }).messages.length, 0);
    const privateRows = readMessages(workspace, actor('receiver'), { recipient_id: 'receiver', private_delivery_token: sent.private_delivery_token }, { includePrivate: true }).messages;
    assert.equal(privateRows.length, 1);
    assert.deepEqual(privateRows[0].evidence_refs, ['secret-ref']);
    assert.equal(readMessages(workspace, actor('receiver'), { recipient_id: 'receiver' }, { includePrivate: false }).messages.length, 0);
    assert.equal(JSON.stringify(readCoordination(workspace)).includes('private detail'), false);
    assert.equal(JSON.stringify(readCoordination(workspace)).includes('msg-fixed'), false);
    assert.equal(JSON.stringify(readCoordination(workspace)).includes('secret-ref'), false);
    const storedHandoff = fs.readFileSync(path.join(workspace, '.engineering-bootstrap', 'coordination', 'handoff.json'), 'utf8');
    assert.equal(storedHandoff.includes('msg-fixed'), false);
    assert.equal(storedHandoff.includes('secret-ref'), false);
    assert.equal(storedHandoff.includes('private detail'), false);
    assert.equal(JSON.parse(storedHandoff).last_event.private_message_redacted, true);
    const publicWait = waitStatus(workspace, wait.wait_id);
    assert.equal(publicWait.wakes[0].private_trigger_redacted, true);
    assert.deepEqual(publicWait.resume_packet.trigger_result_ids, []);
    assert.deepEqual(publicWait.resume_packet.trigger_evidence_ids, []);
    assert.equal(JSON.stringify(publicWait).includes('msg-fixed'), false);
    assert.equal(JSON.stringify(publicWait).includes('secret-ref'), false);
    assert.equal(sendMessage(workspace, actor('sender'), {
      recipient_id: 'receiver', recipient_transport: 'local', privacy_class: 'private', payload: 'private detail', message_id: 'msg-fixed'
    }).result.receipt.payload, undefined);
    assert.throws(() => consumeMessage(workspace, actor('receiver'), { recipient_id: 'receiver', message_id: 'msg-fixed' }, { allowPrivate: false }), /requires-delivery-proof/);
    assert.throws(() => consumeMessage(workspace, actor('other'), { recipient_id: 'receiver', message_id: 'msg-fixed' }), /requires-delivery-proof/);
    consumeMessage(workspace, actor('receiver'), { recipient_id: 'receiver', message_id: 'msg-fixed', private_delivery_token: sent.private_delivery_token });
    assert.equal(readMessages(workspace, actor('receiver'), { recipient_id: 'receiver' }).messages.length, 0);
    assert.equal(readCoordination(workspace).state.mailboxes.receiver, undefined);
  } finally { fs.rmSync(workspace, { recursive: true, force: true }); }
});


test('released waiting task cancels its wait and later dependency completion cannot wake it', () => {
  const workspace = root();
  try {
    plan(workspace, [task('producer-release', 'r-a.txt'), task('consumer-release', 'r-b.txt')]);
    const producer = claimTask(workspace, actor('producer-release'), { task_id: 'producer-release' }).result.receipt;
    const consumer = claimTask(workspace, actor('consumer-release'), { task_id: 'consumer-release' }).result.receipt;
    const wait = registerWait(workspace, actor('consumer-release'), {
      task_id: 'consumer-release', checkpoint_id: 'ctx-release', condition_type: 'task', dependency_ids: ['producer-release'],
      ...proof({ id: consumer.claim_id, fencing_tokens: consumer.fencing_tokens })
    }).result.receipt;
    releaseTask(workspace, actor('consumer-release'), { task_id: 'consumer-release', reason: 'cancelled by operator', ...proof({ id: consumer.claim_id, fencing_tokens: consumer.fencing_tokens }) });
    recordProgress(workspace, actor('producer-release'), {
      task_id: 'producer-release', status: 'completed', summary: 'done after consumer release',
      ...proof({ id: producer.claim_id, fencing_tokens: producer.fencing_tokens })
    });
    const snapshot = readCoordination(workspace);
    assert.equal(snapshot.state.waits.find(item => item.wait_id === wait.wait_id).status, 'cancelled');
    assert.equal(snapshot.state.wakes.filter(item => item.wait_id === wait.wait_id).length, 0);
  } finally { fs.rmSync(workspace, { recursive: true, force: true }); }
});
