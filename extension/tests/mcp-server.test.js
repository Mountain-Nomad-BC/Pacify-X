'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');

const root = path.resolve(__dirname, '..');

test('bundled MCP server exposes first-class catalogs, activity traces, resume, claims, receipts, and layered memory', { timeout: 15000 }, async t => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-mcp-coordination-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  const child = cp.spawn(process.execPath, [path.join(root, 'server', 'index.js')], {
    cwd: root, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env, PX_CONTEXT_PATH: path.join(root, 'tests', 'fixtures', 'context.json'),
      PX_ENGINE_ROOT: root, PX_WORKSPACE_ROOT: workspace, PX_COORDINATION_ROOT: workspace, PX_PYTHON_PATH: 'python'
    }
  });
  const lines = readline.createInterface({ input: child.stdout });
  const messages = []; let stderr = '';
  child.stderr.setEncoding('utf8'); child.stderr.on('data', data => { stderr += data; });
  lines.on('line', line => { if (line.trim()) messages.push(JSON.parse(line)); });
  const send = value => child.stdin.write(`${JSON.stringify(value)}\n`);
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 160; attempt += 1) {
      const found = messages.find(predicate); if (found) return found;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw new Error(`MCP response timeout. stderr=${stderr}`);
  };
  try {
    send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'pacify-test', version: '1.0.0' } } });
    assert.equal((await waitFor(message => message.id === 1)).result.serverInfo.name, 'pacify-x-governed-context');
    send({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
    send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} });
    const listed = await waitFor(message => message.id === 2);
    const byName = new Map(listed.result.tools.map(tool => [tool.name, tool]));
    for (const name of [
      'pacify_context_snapshot', 'pacify_control_plane_summary', 'pacify_catalog_query', 'pacify_git_context',
      'pacify_tool_conflict_status', 'pacify_coordination_status', 'pacify_activity_observability', 'pacify_activity_emit', 'pacify_resume_handoff', 'pacify_task_handoff',
      'pacify_parallel_plan_create', 'pacify_task_claim', 'pacify_task_progress', 'pacify_task_reconcile',
      'pacify_task_release', 'pacify_memory_capture', 'pacify_memory_observability', 'pacify_claim_renew', 'pacify_work_stop_diagnostics',
      'pacify_work_room', 'pacify_worker_adapter_doctor', 'pacify_team_pack_preview', 'pacify_team_pack_stage',
      'pacify_enterprise_status', 'pacify_enterprise_readiness', 'pacify_enterprise_pack_set', 'pacify_enterprise_target_configure',
      'pacify_environment_inventory', 'pacify_environment_extension_detail', 'pacify_billable_guardrail_evaluate',
      'pacify_capability_manifest', 'pacify_graph_query', 'pacify_hardware_telemetry', 'pacify_plugin_catalog', 'pacify_agent_readiness', 'pacify_mcp_instrumentation_status'
    ]) assert.equal(byName.has(name), true, name);
    for (const name of ['pacify_context_snapshot', 'pacify_catalog_query', 'pacify_coordination_status', 'pacify_activity_observability', 'pacify_memory_observability', 'pacify_resume_handoff', 'pacify_work_stop_diagnostics', 'pacify_work_room', 'pacify_worker_adapter_doctor', 'pacify_team_pack_preview', 'pacify_enterprise_status', 'pacify_environment_inventory', 'pacify_environment_extension_detail', 'pacify_billable_guardrail_evaluate', 'pacify_capability_manifest', 'pacify_graph_query', 'pacify_hardware_telemetry', 'pacify_plugin_catalog', 'pacify_agent_readiness', 'pacify_mcp_instrumentation_status']) {
      assert.equal(byName.get(name).annotations.readOnlyHint, true);
    }
    for (const name of ['pacify_activity_emit', 'pacify_parallel_plan_create', 'pacify_task_claim', 'pacify_task_progress', 'pacify_task_reconcile', 'pacify_memory_capture', 'pacify_enterprise_readiness', 'pacify_enterprise_pack_set', 'pacify_enterprise_target_configure']) {
      assert.equal(byName.get(name).annotations.readOnlyHint, false);
      assert.equal(byName.get(name).annotations.destructiveHint, false);
    }

    const actor = { actor_id: 'mcp-agent', session_id: 'mcp-session', harness: 'test-harness' };
    send({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'pacify_parallel_plan_create', arguments: {
      ...actor, objective: 'MCP parallel plan', tasks: [{ id: 'docs', title: 'Docs', claims: ['docs/'] }]
    } } });
    const created = await waitFor(message => message.id === 3);
    assert.equal(created.result.structuredContent.result.receipt.tasks, 1);
    send({ jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'pacify_task_claim', arguments: { ...actor, task_id: 'docs' } } });
    const claimed = await waitFor(message => message.id === 4);
    assert.equal(claimed.result.structuredContent.result.receipt.task_id, 'docs');
    const claimReceipt = claimed.result.structuredContent.result.receipt;
    send({ jsonrpc: '2.0', id: 6, method: 'tools/call', params: { name: 'pacify_claim_renew', arguments: { ...actor, claim_id: claimReceipt.claim_id, fencing_tokens: claimReceipt.fencing_tokens, ttl_minutes: 30 } } });
    const renewed = await waitFor(message => message.id === 6);
    assert.equal(renewed.result.structuredContent.result.receipt.claim_id, claimReceipt.claim_id);
    send({ jsonrpc: '2.0', id: 5, method: 'tools/call', params: { name: 'pacify_coordination_status', arguments: {} } });
    const status = await waitFor(message => message.id === 5);
    assert.equal(status.result.structuredContent.state.claims.length, 1);
    send({ jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'pacify_memory_capture', arguments: { ...actor, layer: 'project', kind: 'decision', content: 'MCP-visible bounded memory' } } });
    await waitFor(message => message.id === 7);
    send({ jsonrpc: '2.0', id: 8, method: 'tools/call', params: { name: 'pacify_memory_observability', arguments: { query: 'bounded memory', include_content: true } } });
    const memory = await waitFor(message => message.id === 8);
    assert.equal(memory.result.structuredContent.canonical, false);
    assert.equal(memory.result.structuredContent.records[0].content, 'MCP-visible bounded memory');
    send({ jsonrpc: '2.0', id: 9, method: 'tools/call', params: { name: 'pacify_activity_emit', arguments: { ...actor, correlation_id: 'agent-trace-test', category: 'verification', operation: 'verification.acceptance', status: 'succeeded', effect: 'observe', scope_refs: ['tests/mcp-server.test.js'], metadata: { check_count: 1, prompt: 'must be redacted' } } } });
    const emitted = await waitFor(message => message.id === 9);
    assert.equal(emitted.result.structuredContent.recorded, true);
    assert.equal(emitted.result.structuredContent.event.metadata.prompt, '[redacted]');
    send({ jsonrpc: '2.0', id: 10, method: 'tools/call', params: { name: 'pacify_activity_observability', arguments: { query: 'verification.acceptance', limit: 20 } } });
    const activity = await waitFor(message => message.id === 10);
    assert.equal(activity.result.structuredContent.events.some(event => event.correlation_id === 'agent-trace-test'), true);
    assert.equal(activity.result.structuredContent.events.every(event => event.content_captured === false), true);
    send({ jsonrpc: '2.0', id: 11, method: 'tools/call', params: { name: 'pacify_mcp_instrumentation_status', arguments: {} } });
    const instrumentation = await waitFor(message => message.id === 11);
    assert.equal(instrumentation.result.structuredContent.status, 'healthy');
    assert.equal(instrumentation.result.structuredContent.registered_tools.length, byName.size);
    assert.equal(instrumentation.result.structuredContent.identity.self_asserted_calls > 0, true);
    assert.equal(instrumentation.result.structuredContent.identity.unattested_calls > 0, true);
  } finally { child.kill(); }
});
