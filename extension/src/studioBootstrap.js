'use strict';

const STARTER_AGENT = Object.freeze({
  agent_id: 'agent:pacify-x-starter',
  version: '1.0.0',
  project_id: 'project:current',
  owner: 'human:vscode-local-user',
  harness_id: 'harness:px',
  instructions: 'Complete the supplied bounded objective using only admitted local capabilities and effect grants.\n',
  capability_binding_ids: ['binding:pacify-x-starter'],
  effect_grant_ids: ['grant:pacify-x-starter'],
  required_tests: ['identity', 'sandbox'],
  grants: [{
    grant_id: 'grant:pacify-x-starter', subject_id: 'agent:pacify-x-starter', effects: ['read'],
    scope_roots: ['workspace:current'], approved_by: 'human:vscode-local-user',
    evidence_refs: ['receipt:studio-setup'], state: 'admitted'
  }],
  bindings: [{
    binding_id: 'binding:pacify-x-starter', subject_kind: 'agent', subject_id: 'agent:pacify-x-starter',
    capability_id: 'capability:identity', capability_version: '1.0.0',
    effect_grant_ids: ['grant:pacify-x-starter'], credential_namespace: null,
    cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted',
    evidence_refs: ['receipt:studio-setup']
  }]
});

const STARTER_WORKFLOW = Object.freeze({
  workflow_id: 'workflow:pacify-x-starter',
  version: '1.0.0',
  owner: 'human:vscode-local-user',
  nodes: [{
    node_id: 'step:identity', kind: 'task', config: {},
    executor_binding_id: 'binding:pacify-x-workflow',
    inputs: [{ name: 'value', data_type: 'string', required: true }],
    outputs: [{ name: 'value', data_type: 'string', required: true }],
    effect_grant_ids: ['grant:pacify-x-workflow'], failure_policy: 'fail-closed',
    timeout_seconds: 30, retry_limit: 0, approval_required: false
  }],
  edges: [],
  editor_layout: { 'step:identity': { x: 120, y: 160 } },
  grants: [{
    grant_id: 'grant:pacify-x-workflow', subject_id: 'workflow:pacify-x-starter', effects: ['read'],
    scope_roots: ['workspace:current'], approved_by: 'human:vscode-local-user',
    evidence_refs: ['receipt:studio-setup'], state: 'admitted'
  }],
  bindings: [{
    binding_id: 'binding:pacify-x-workflow', subject_kind: 'workflow', subject_id: 'workflow:pacify-x-starter',
    capability_id: 'capability:identity', capability_version: '1.0.0',
    effect_grant_ids: ['grant:pacify-x-workflow'], credential_namespace: null,
    cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted',
    evidence_refs: ['receipt:studio-setup']
  }],
  executor_adapters: { 'binding:pacify-x-workflow': 'identity' }
});

function clone(value) { return JSON.parse(JSON.stringify(value)); }

async function approvedOperation(bridge, kind, operation, payload) {
  const exact = clone(payload);
  const capability = await bridge.issueStudioApproval(kind, operation, exact);
  if (!capability?.approval_capability) throw new Error(`studio-setup-approval-unavailable:${kind}:${operation}`);
  return bridge.studioOperation(kind, operation, { ...exact, approval_capability: capability.approval_capability });
}

async function setupStudio(bridge, { progress = () => {} } = {}) {
  if (!bridge || typeof bridge.issueStudioApproval !== 'function' || typeof bridge.studioOperation !== 'function') {
    throw new TypeError('studio-setup-bridge-invalid');
  }
  const agent = clone(STARTER_AGENT);
  const workflow = clone(STARTER_WORKFLOW);
  const receipts = {};
  const step = async (id, kind, operation, payload, approved = true) => {
    progress(id);
    const result = approved
      ? await approvedOperation(bridge, kind, operation, payload)
      : await bridge.studioOperation(kind, operation, clone(payload));
    receipts[id] = result;
    return result;
  };

  await step('agent_create', 'agent', 'create', agent);
  const agentTest = await step('agent_test', 'agent', 'test', agent);
  if (agentTest?.passed !== true) throw new Error('studio-setup-agent-tests-failed');
  await step('agent_authority', 'agent', 'register-authority', agent);
  const agentAdmission = await step('agent_admit', 'agent', 'admit', agent);
  if (agentAdmission?.decision !== 'admitted') throw new Error('studio-setup-agent-admission-failed');
  const agentRun = await step('agent_run', 'agent', 'run', { ...agent, task: { objective: 'Verify the local Studio agent execution path.' } });
  if (agentRun?.run_outcome !== 'succeeded') throw new Error('studio-setup-agent-run-failed');

  await step('workflow_create', 'workflow', 'create', workflow);
  await step('workflow_authority', 'workflow', 'register-authority', workflow);
  const workflowAdmission = await step('workflow_validate', 'workflow', 'validate', workflow);
  if (workflowAdmission?.decision !== 'admitted') throw new Error('studio-setup-workflow-admission-failed');
  const workflowDryRun = await step('workflow_dry_run', 'workflow', 'dry-run', workflow, false);
  if (workflowDryRun?.effects_executed !== false) throw new Error('studio-setup-workflow-dry-run-invalid');
  const workflowRun = await step('workflow_run', 'workflow', 'run', { ...workflow, run_inputs: { 'step:identity.value': 'Studio is operational.' } });
  if (workflowRun?.run_state !== 'succeeded') throw new Error('studio-setup-workflow-run-failed');

  return {
    schema_version: 'px.studio-setup-result/1.0',
    ready: true,
    agent: { identity: agent.agent_id, version: agent.version, decision: agentAdmission.decision, run_id: agentRun.run_id, run_outcome: agentRun.run_outcome },
    workflow: { identity: workflow.workflow_id, version: workflow.version, decision: workflowAdmission.decision, run_id: workflowRun.run_id, run_state: workflowRun.run_state },
    completed_steps: Object.keys(receipts)
  };
}

module.exports = { STARTER_AGENT, STARTER_WORKFLOW, approvedOperation, setupStudio };
