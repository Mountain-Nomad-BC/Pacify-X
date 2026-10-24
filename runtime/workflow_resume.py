"""Validate native workflow checkpoints before reusing completed work.

This is a read-side guard, not a workflow, approval, or effect authority. The
native DurableRunControl authenticates the checkpoint; StudioAuthorityStore
resolves live grants. Unknown side-effect outcomes are never executed again.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .effect_intent import EffectIntentLedger
from .json_io import bounded_canonical_json_bytes
from .studio_authority import StudioAuthorityStore
from .studio_models import WorkflowDefinition, digest
from .studio_run_control import DurableRunControl

MAX_NODES = 512
READ_ONLY_EFFECTS = frozenset({"read", "inspect", "list", "observe", "query"})


class WorkflowResumeRejected(PermissionError):
    """Checkpoint reuse lacks exact output, dependency, or effect evidence."""


@dataclass(frozen=True, slots=True)
class WorkflowResumeDecision:
    run_id: str
    control_sequence: int
    completed_nodes: tuple[str, ...]
    ready_nodes: tuple[str, ...]
    checkpoint_sha256: str
    authority_hashes: Mapping[str, str]

    def as_dict(self) -> dict:
        return {
            "schema_version": "px.workflow-resume-decision/1.0",
            "run_id": self.run_id,
            "control_sequence": self.control_sequence,
            "completed_nodes": list(self.completed_nodes),
            "ready_nodes": list(self.ready_nodes),
            "checkpoint_sha256": self.checkpoint_sha256,
            "authority_hashes": dict(self.authority_hashes),
            "authority_granted": False,
        }


def validate_workflow_resume(
    definition: WorkflowDefinition,
    run_control: DurableRunControl,
    run_id: str,
    *,
    expected_revision_sha256: str,
    expected_request_sha256: str,
    expected_control_sequence: int | None = None,
    effect_intents: EffectIntentLedger | None = None,
    revalidate_skipped: Callable[[str, Mapping[str, Mapping]], bool] | None = None,
) -> WorkflowResumeDecision:
    """Authenticate and inspect the current native checkpoint, without writes.

    Call after worker closure and before the running transition. The host must
    retain the returned control sequence for its transition fence. Mutating
    completed nodes need recorded native committed intents, never a boolean
    approval or a checkpoint naming a node. Legacy uncertain nodes stay blocked.
    """
    if not isinstance(definition, WorkflowDefinition):
        raise TypeError("resume requires a native WorkflowDefinition")
    if type(run_control) is not DurableRunControl:
        raise TypeError("resume requires the canonical durable run owner")
    if type(run_control.authority) is not StudioAuthorityStore:
        raise TypeError("resume requires canonical Studio authority")
    if effect_intents is not None and type(effect_intents) is not EffectIntentLedger:
        raise TypeError("effect evidence requires the canonical intent owner")
    if effect_intents is not None and effect_intents.root != run_control.project_root:
        raise WorkflowResumeRejected("effect ledger belongs to another project")
    state = run_control.read(run_id)
    if expected_control_sequence is not None and (
            type(expected_control_sequence) is not int
            or expected_control_sequence < 1
            or state.get("sequence") != expected_control_sequence):
        raise WorkflowResumeRejected("checkpoint snapshot was superseded before validation")
    expected = {"kind": "workflow", "subject_id": definition.workflow_id,
                "version": definition.version, "owner": definition.owner,
                "revision_sha256": expected_revision_sha256,
                "request_sha256": expected_request_sha256}
    if any(state.get(key) != value for key, value in expected.items()):
        raise WorkflowResumeRejected("resume identity/revision/request differs from native state")
    if state.get("state") not in {"queued", "paused", "interrupted"}:
        raise WorkflowResumeRejected("native workflow is not resumable")
    checkpoint = state.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise WorkflowResumeRejected("checkpoint must be an object")
    bounded_canonical_json_bytes(dict(checkpoint), max_bytes=8 * 1024 * 1024)
    nodes = {node.node_id: node for node in definition.nodes}
    if len(nodes) != len(definition.nodes) or len(nodes) > MAX_NODES:
        raise WorkflowResumeRejected("workflow node denominator is invalid")
    completed = checkpoint.get("completed_nodes", [])
    results = checkpoint.get("results", {})
    receipts = checkpoint.get("node_receipts", [])
    if (type(completed) is not list or len(completed) > MAX_NODES
            or any(type(x) is not str for x in completed)
            or len(completed) != len(set(completed))
            or not set(completed) <= set(nodes)
            or not isinstance(results, Mapping)
            or set(results) != set(completed)
            or any(not isinstance(x, Mapping) for x in results.values())
            or type(receipts) is not list or len(receipts) != len(completed)
            or any(not isinstance(x, Mapping) for x in receipts)):
        raise WorkflowResumeRejected("completed/output/receipt denominators differ")
    by_id = {row.get("node_id"): row for row in receipts}
    if len(by_id) != len(receipts) or set(by_id) != set(completed):
        raise WorkflowResumeRejected("completed node receipts are duplicate or missing")
    dependencies = {identity: set() for identity in nodes}
    for edge in definition.edges:
        dependencies[edge.target_node].add(edge.source_node)
    if any(not dependencies[identity] <= set(completed) for identity in completed):
        raise WorkflowResumeRejected("completed nodes are not dependency closed")
    ready = tuple(sorted(identity for identity in nodes
                         if identity not in completed and dependencies[identity] <= set(completed)))
    if checkpoint.get("ready_nodes", []) != list(ready):
        raise WorkflowResumeRejected("checkpoint ready-node projection is stale")
    if checkpoint.get("next_node") != (ready[0] if ready else None):
        raise WorkflowResumeRejected("checkpoint next-node projection is stale")
    hashes = {}
    authority = run_control.authority
    for identity in sorted(completed):
        node, receipt, output = nodes[identity], by_id[identity], results[identity]
        if receipt.get("kind") != node.kind:
            raise WorkflowResumeRejected("completed node kind differs from current definition")
        disposition = receipt.get("state")
        if disposition == "skipped":
            if (output or receipt.get("attempts") != []
                    or receipt.get("skip_reason") != "incoming_condition_disabled"
                    or revalidate_skipped is None
                    or revalidate_skipped(identity, results) is not True):
                raise WorkflowResumeRejected("skipped branch was not revalidated")
        elif disposition == "failed-continued":
            if node.failure_policy != "continue" or output:
                raise WorkflowResumeRejected("continued failure output is invalid")
        elif disposition == "succeeded":
            if receipt.get("output_sha256") != digest(dict(output)):
                raise WorkflowResumeRejected("checkpoint output digest differs from completed receipt")
        else:
            raise WorkflowResumeRejected("failed or unknown work cannot be reused as completed")
        binding, binding_sha = authority.resolve_binding(
            node.executor_binding_id, subject_kind="workflow", subject_id=definition.workflow_id)
        executor, executor_sha = authority.resolve_executor(node.executor_binding_id)
        if set(binding.get("effect_grant_ids", [])) != set(node.effect_grant_ids):
            raise WorkflowResumeRejected("node grant binding changed")
        hashes[f"binding:{node.executor_binding_id}"] = binding_sha
        hashes[f"executor:{node.executor_binding_id}"] = executor_sha
        effects = set()
        effect_scopes: dict[str, set[str]] = {}
        for grant_id in node.effect_grant_ids:
            grant, grant_sha = authority.resolve_grant(grant_id, subject_id=definition.workflow_id)
            effects.update(grant.get("effects", []))
            for effect in grant.get("effects", []):
                effect_scopes.setdefault(effect, set()).update(
                    str(scope).strip().replace("\\", "/").rstrip("/").casefold() or "*"
                    for scope in grant.get("scope_roots", []))
            hashes[f"grant:{grant_id}"] = grant_sha
        attempts = receipt.get("attempts")
        if type(attempts) is not list or len(attempts) > node.retry_limit + 1:
            raise WorkflowResumeRejected("completed receipt attempt history is invalid")
        if disposition == "succeeded":
            if not attempts or not isinstance(attempts[-1], Mapping):
                raise WorkflowResumeRejected("successful node lacks actual worker evidence")
            final = attempts[-1]
            if (final.get("status") != "exited" or final.get("exit_code") != 0
                    or final.get("tree_closed") is not True
                    or final.get("adapter_id") != executor.get("adapter_id")
                    or final.get("node_config_sha256") != digest(dict(node.config))):
                raise WorkflowResumeRejected("successful worker/config/adapter evidence differs")
        if disposition != "skipped" and not effects <= READ_ONLY_EFFECTS:
            proofs = receipt.get("committed_effect_intents")
            if effect_intents is None or type(proofs) is not list or not 1 <= len(proofs) <= 64:
                raise WorkflowResumeRejected("completed mutating node lacks native committed effect evidence")
            witnessed = set()
            keys = set()
            for proof in proofs:
                if not isinstance(proof, Mapping) or set(proof) != {
                        "idempotency_key", "execution_id", "effect", "result_sha256"}:
                    raise WorkflowResumeRejected("committed effect reference shape is invalid")
                key = proof["idempotency_key"]
                if type(key) is not str or key in keys:
                    raise WorkflowResumeRejected("committed effect references are duplicate")
                keys.add(key)
                # A workflow-level intent belongs to this exact run. Child
                # provider/group executions need their own authenticated parent
                # linkage before a future adapter can widen this rule.
                if proof["execution_id"] != run_id:
                    raise WorkflowResumeRejected("effect intent belongs to another execution")
                observed = effect_intents.fence(key)
                if (observed.get("disposition") != "committed"
                        or any(observed.get(name) != proof[name]
                               for name in ("execution_id", "effect", "result_sha256"))):
                    raise WorkflowResumeRejected("native effect outcome is absent or indeterminate")
                scopes = observed.get("scopes")
                if type(scopes) is not list or not scopes or any(type(x) is not str for x in scopes):
                    raise WorkflowResumeRejected("native committed effect lacks scope evidence")
                normalized_scopes = {
                    scope.strip().replace("\\", "/").rstrip("/").casefold() or "*"
                    for scope in scopes}
                if not effect_scopes.get(proof["effect"], set()) <= normalized_scopes:
                    raise WorkflowResumeRejected("native effect scopes do not cover the current grant")
                witnessed.add(proof["effect"])
            if not effects - READ_ONLY_EFFECTS <= witnessed:
                raise WorkflowResumeRejected("mutating grant effects are not completely witnessed")
    return WorkflowResumeDecision(run_id, state["sequence"], tuple(sorted(completed)),
                                  ready, digest(dict(checkpoint)), hashes)
