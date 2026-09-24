'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

function text(relative) { return fs.readFileSync(path.join(__dirname, '..', relative), 'utf8'); }

test('MCP surface exposes bounded cognitive query and durable coordination tools through PX owners', () => {
  const source = text('server/source.mjs');
  for (const name of ['pacify_cognitive_query','pacify_message_send','pacify_message_read','pacify_message_consume','pacify_wait_register','pacify_wait_status','pacify_wake_ack']) {
    assert.match(source, new RegExp(`registerTool\\('${name}'`));
  }
  assert.match(source, /runApi\(args\)/);
  assert.match(source, /top_per_category.*min\(1\).*max\(3\)/s);
  assert.match(source, /registerWait, waitStatus, acknowledgeWake, sendMessage, readMessages, consumeMessage/);
  assert.doesNotMatch(source, /localhost.*llama|llama-server.*pacify_cognitive_query/s);
});

test('workspace commissioning persists one metadata-only inventory and extension changes refresh only an established inventory', () => {
  const source = text('src/extension.js');
  assert.match(source, /refreshEnvironment\('workspace-commissioning', false, 'approved'/);
  assert.match(source, /const commissioned = root \? Boolean\(readEnvironmentInventory\(root\)\.inventory\) : false/);
  assert.match(source, /setTimeout\(\(\) => \{ extensionInventoryRefreshTimer = undefined; void runRefresh\('approved'\); \}, 750\)/);
  assert.match(source, /clearTimeout\(extensionInventoryRefreshTimer\)/);
});
