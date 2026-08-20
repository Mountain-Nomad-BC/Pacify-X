'use strict';

const READ_EFFECTS = new Set(['read', 'read_local', 'workspace-read', 'observe', 'host-ui']);
const WRITE_EFFECTS = new Set([
  'write_workspace', 'workspace-write', 'filesystem-write', 'configuration-write', 'clipboard-write',
  'install_tool', 'network', 'run_service', 'process', 'secret_access', 'migration', 'destructive', 'destructive-filesystem'
]);
const EXECUTORS = new Set(['codex-host', 'px-owned-executor']);

function decideAuthority(input = {}) {
  const reasons = [];
  const executor = String(input.executor || '');
  const effects = new Set((input.effects || []).map(String));
  const nonRead = [...effects].some(effect => !READ_EFFECTS.has(effect));
  const workspaceWrite = [...effects].some(effect => [
    'write_workspace', 'workspace-write', 'filesystem-write', 'configuration-write', 'destructive', 'destructive-filesystem'
  ].includes(effect));
  if (!EXECUTORS.has(executor)) reasons.push('executor is not an admitted operation owner');
  if ([...effects].some(effect => !READ_EFFECTS.has(effect) && !WRITE_EFFECTS.has(effect))) reasons.push('request contains unknown effects');
  if (input.observedOnly && nonRead) reasons.push('observation cannot authorize or claim a non-read effect');
  if (nonRead && !input.userApprovalId) reasons.push('non-read effects require current user approval');
  if (nonRead && !input.pxPolicyDecisionId) reasons.push('non-read effects require a PX policy decision');
  if (nonRead && !input.idempotencyKey) reasons.push('non-read effects require an idempotency key');
  if (workspaceWrite && !(input.claimId && input.claimStatus === 'active')) reasons.push('workspace mutation requires an active repository claim');
  if (executor === 'px-owned-executor' && !input.explicitDelegation) reasons.push('PX-owned execution requires explicit delegation');
  const active = [...new Set((input.activeExecutors || []).map(String))];
  if (active.some(owner => !EXECUTORS.has(owner))) reasons.push('active executor set contains an unadmitted owner');
  if (active.some(owner => owner !== executor)) reasons.push('overlapping active executor authority is forbidden');
  if (executor === 'px-owned-executor' && active.includes('codex-host')) reasons.push('PX must not start a nested executor inside the Codex host');
  return Object.freeze({
    allowed: reasons.length === 0,
    executorOwner: reasons.length === 0 ? executor : null,
    reasons: Object.freeze([...new Set(reasons)]),
    requiresUserApproval: nonRead,
    requiresClaim: workspaceWrite
  });
}

function codexHostHandoffDecision({ git, hasWorkspaceClaim = false, requestedEffect = 'workspace-read' } = {}) {
  const gitDecision = git && Array.isArray(git.reasons)
    ? git
    : { allowed: !git?.operation || git.operation === 'none', reasons: git?.operation && git.operation !== 'none' ? [`git-operation:${git.operation}`] : [] };
  const reasons = [...(gitDecision.reasons || [])];
  if (requestedEffect === 'workspace-write' && !hasWorkspaceClaim) reasons.push('workspace-write requires an active repository claim');
  return Object.freeze({
    allowed: gitDecision.allowed !== false && reasons.length === 0,
    mode: 'host-context-handoff',
    executorOwner: 'codex-host',
    extensionExecutes: false,
    requestedEffect,
    reasons: Object.freeze([...new Set(reasons)])
  });
}

module.exports = { decideAuthority, codexHostHandoffDecision, READ_EFFECTS, WRITE_EFFECTS, EXECUTORS };
