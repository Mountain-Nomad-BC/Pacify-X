'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { ActivationTransaction } = require('../src/activationTransaction');

test('activation transaction rolls back all registrations in reverse order', () => {
  const context = { subscriptions: [{ dispose() {} }] };
  const disposed = [];
  const transaction = new ActivationTransaction(context);
  transaction.own({ dispose: () => disposed.push('first') });
  transaction.own({ dispose: () => disposed.push('second') });
  transaction.rollback();
  assert.deepEqual(disposed, ['second', 'first']);
  assert.equal(context.subscriptions.length, 1);
  transaction.rollback();
  assert.deepEqual(disposed, ['second', 'first']);
});

test('committed activation stays context-owned and later registrations are context-owned', () => {
  const context = { subscriptions: [] };
  const transaction = new ActivationTransaction(context);
  transaction.own({ dispose() {} });
  transaction.commit();
  transaction.rollback();
  transaction.own({ dispose() {} });
  assert.equal(context.subscriptions.length, 2);
});

test('every injected activation boundary returns the host to its exact registration baseline', () => {
  const boundaryCount = 24;
  for (let failAfter = 1; failAfter <= boundaryCount; failAfter += 1) {
    const retained = { dispose() {} };
    const context = { subscriptions: [retained] };
    const disposed = [];
    const transaction = new ActivationTransaction(context, {
      faultInjector: ({ registered }) => { if (registered === failAfter) throw new Error(`activation-boundary-${failAfter}`); }
    });
    assert.throws(() => {
      try {
        for (let index = 1; index <= boundaryCount; index += 1) transaction.own({ dispose: () => disposed.push(index) });
        transaction.commit();
      } catch (error) {
        transaction.rollback();
        throw error;
      }
    }, new RegExp(`activation-boundary-${failAfter}`));
    assert.deepEqual(context.subscriptions, [retained]);
    assert.equal(disposed.length, failAfter);
  }
});
