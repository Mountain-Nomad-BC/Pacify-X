'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { actionIdentity, matchesVariant } = require('../scripts/run-contained-ui-action-walk');
const { CHAIN_STAGES, isCompleteInteractionChain } = require('../scripts/operational-ui-control-records');

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

test('interaction chains complete only when every admitted stage is observed or not applicable', () => {
  const complete = { stages: CHAIN_STAGES.map((stage, index) => ({ stage, status: index % 2 ? 'observed' : 'not_applicable' })) };
  assert.equal(isCompleteInteractionChain(complete), true);
  complete.stages[3].status = 'not_attempted';
  assert.equal(isCompleteInteractionChain(complete), false);
  assert.equal(isCompleteInteractionChain({ stages: complete.stages.slice(1) }), false);
});
