'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { actionIdentity, matchesVariant } = require('../scripts/run-contained-ui-action-walk');

test('contained action walker resolves dynamic repair and repeatable row identities exactly', () => {
  assert.deepEqual(actionIdentity({ label: 'dynamicRepair.refreshEnvironment' }), {
    action: 'refreshEnvironment', variants: []
  });
  assert.deepEqual(actionIdentity({ label: 'inspectActivityEvent.row' }), {
    action: 'inspectActivityEvent', variants: ['row']
  });
  assert.equal(matchesVariant({ eventId: 'event:one' }, ['row']), true);
  assert.equal(matchesVariant({ recordKey: 'record:one' }, ['row']), true);
  assert.equal(matchesVariant({ kind: 'agent' }, ['workflow']), false);
});
