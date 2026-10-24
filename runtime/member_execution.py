"""Canonical bridge from model-group member execution to the provider gateway.

``AgentRuntimeController.execute_governed_group`` takes an explicit
``member_executor`` callback, but until now no *production* member executor
existed — only tests supplied one. This module is that production executor: it
turns one prepared :class:`MemberExecutionInput` into exactly one governed
provider invocation through the canonical gateway.

It invents nothing. A caller must supply:

* an admitted ``ProviderInvocationGateway``;
* an immutable execution ``policy`` for this plan;
* an ``adapter_for(model_id)`` resolver that returns the admitted adapter for the
  member's exact model, or ``None`` when no adapter is configured (an
  unconfigured provider stays explicitly unavailable, never silently rerouted);
* the member's ``ProviderRequest`` identity fields (project/actor/session).

The executor returns the bounded provider output value, which the group owner then
commits as an immutable branch artifact. It grants no authority of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Callable, Mapping

from .provider_gateway import (
    ProviderInvocationError,
    ProviderRequest,
    execute_provider_request,
)

SCHEMA_VERSION = "px.member-executor/1.0"


class MemberExecutionUnavailable(RuntimeError):
    """Raised when a member's provider/adapter is not configured.

    This is an explicit *unavailable* state, not a silent fallback: the group
    owner records the member as not-admitted rather than substituting a different
    provider.
    """


def build_provider_member_executor(
    *,
    gateway,
    policy: Mapping[str, object] | Callable[[str], Mapping[str, object]],
    adapter_for: Callable[[str], object | None],
    project_id: str,
    actor_id: str,
    accountable_owner: str,
    session_for: Callable[[str], str | None] | None = None,
    correlation_for: Callable[[str], str] | None = None,
    invocation_for: Callable[[str], str] | None = None,
    containment=None,
    containment_required: bool = False,
    output_bytes_for: Callable[[str], int] | None = None,
    project_root=None,
    workflow_effect_receipt=None,
    workflow_task_plan=None,
    workflow_agent_spec=None,
    workflow_placements=None,
) -> Callable[..., object]:
    """Return a member executor that invokes one member through the gateway.

    The returned callback matches the group owner's exact signature:
    ``member_executor(invocation, device=..., batch_size=..., execution_context=...,
    cancellation_token=...)``.

    ``containment`` is the canonical Gremlin Nanny instance (or ``None``). When
    ``containment_required`` is True the executor refuses to start a provider
    request unless the member's execution has a *verified* containment proof for
    the exact execution id it was released under. The workload can never set that
    proof: it is read from the containment authority through the execution context,
    never asserted by the member.
    """
    if not callable(getattr(gateway, "invoke", None)):
        raise TypeError("member executor requires an admitted provider gateway")
    if not isinstance(policy, Mapping) and not callable(policy):
        raise TypeError("member executor requires an immutable execution policy")
    if not callable(adapter_for):
        raise TypeError("member executor requires an adapter resolver")
    for name, value in (("project_id", project_id), ("actor_id", actor_id),
                        ("accountable_owner", accountable_owner)):
        if type(value) is not str or not value.strip():
            raise TypeError(f"member executor requires a bounded {name}")

    def member_executor(invocation, *, device=None, batch_size=None,
                        execution_context=None, cancellation_token=None):
        model_id = getattr(invocation, "model_id", None)
        if type(model_id) is not str or not model_id.strip():
            raise TypeError("member invocation must expose an exact model_id")
        adapter = adapter_for(model_id)
        if adapter is None:
            raise MemberExecutionUnavailable(
                "no admitted adapter is configured for member model " + model_id
            )
        from .group_provider_adapters import GroupProviderBinding, RemoteGroupProviderBinding
        from .remote_model_attachment import RemoteModelAttachment
        from .model_group_preparation import MemberExecutionInput, context_sha256
        from .execution_context import ExecutionContext
        from .model_protocol import CanonicalModelRequest
        remote = type(adapter) is RemoteGroupProviderBinding
        if type(adapter) not in (GroupProviderBinding, RemoteGroupProviderBinding) or type(invocation) is not MemberExecutionInput:
            raise MemberExecutionUnavailable("member requires a native configured provider binding and prepared invocation")
        if type(execution_context) is not ExecutionContext:
            raise MemberExecutionUnavailable("member requires its canonical execution context")
        selected_policy = policy(model_id) if callable(policy) else policy
        if not isinstance(selected_policy, Mapping):
            raise MemberExecutionUnavailable("member has no exact immutable execution policy")
        adapter.assert_current()
        attachment = invocation.attachment
        if not remote and (adapter.model_id != model_id or attachment.model_id != model_id or
                adapter.artifact_sha256 != attachment.artifact_sha256):
            raise PermissionError("member attachment differs from actual running provider artifact")
        if execution_context.project_id != project_id:
            raise PermissionError("member execution context belongs to a different project")
        # Containment-before-release: a member that requires containment must have
        # a verified proof bound to its exact execution id. The proof comes from
        # the containment authority, never from the member's own assertion.
        execution_id = getattr(execution_context, "execution_id", None)
        if containment_required:
            from .gremlin.enrollment import ContainmentRequired, require_containment_proof

            if containment is None:
                raise ContainmentRequired(
                    "containment is required but no Gremlin Nanny is configured for this member"
                )
            if type(execution_id) is not str or not execution_id.strip():
                raise ContainmentRequired(
                    "containment is required but the member execution context has no execution identity"
                )
            try:
                proof = require_containment_proof(
                    containment, execution_id=execution_id, required=True
                )
            except ContainmentRequired:
                raise
        # A cancelled/deadline member must not start a provider request.
        if cancellation_token is not None and callable(cancellation_token) and cancellation_token():
            raise MemberExecutionUnavailable("member execution was cancelled before provider invocation")
        _ = proof if containment_required else None

        invocation_id = invocation_for(model_id) if invocation_for else execution_context.execution_id
        session_id = session_for(model_id) if session_for else execution_context.session_id
        remaining_ms = int((datetime.fromisoformat(execution_context.deadline_utc.replace("Z", "+00:00"))
                            - datetime.now(timezone.utc)).total_seconds() * 1000)
        if remaining_ms < 1:
            raise MemberExecutionUnavailable("member deadline expired before provider invocation")
        context = invocation.context
        if context.get("project_id") != project_id or context.get("model_id") != model_id:
            raise PermissionError("prepared member context identity differs")
        if context_sha256(context) != invocation.context_sha256:
            raise PermissionError("prepared member context digest differs")
        if remote:
            if (type(attachment) is not RemoteModelAttachment or device != 'remote_provider' or batch_size is not None or
                    project_root is None or workflow_effect_receipt is None or workflow_task_plan is None or
                    workflow_agent_spec is None or workflow_placements is None):
                raise PermissionError('remote member requires its native placement and signed workflow effect owner')
            from .remote_member_execution import execute_remote_member
            return execute_remote_member(root=project_root, gateway=gateway, binding=adapter,
                selected_policy=selected_policy, invocation=invocation, context=execution_context,
                actor_id=actor_id, accountable_owner=accountable_owner,
                output_limit=output_bytes_for(model_id) if output_bytes_for else 524288,
                cancel_requested=cancellation_token, signed_task=workflow_effect_receipt,
                task_plan=workflow_task_plan, spec=workflow_agent_spec, placements=workflow_placements)
        # Deliver the exact prepared semantic context as bounded data; do not
        # splice placement objects, mutable attachments, or tool grants into HTTP.
        content = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        profile = adapter.profile
        if device not in {"cpu", "cuda"} or (device == "cpu") != profile.cpu_only:
            raise PermissionError("member placement differs from the running frozen model profile")
        if batch_size is not None and batch_size != profile.batch_size:
            raise PermissionError("member batch placement differs from the running frozen model profile")
        output_limit = output_bytes_for(model_id) if output_bytes_for else 524288
        if type(output_limit) is not int or not 1 <= output_limit <= 524288:
            raise PermissionError("member output byte budget is not a native bounded role limit")
        canonical = CanonicalModelRequest(
            request_id=invocation_id, session_id=session_id, client_id=actor_id,
            operation_id=execution_context.execution_id, privacy=attachment.privacy,
            route=adapter.adapter_id, messages=({"role": "user", "content": content},), tools=(),
            max_output_tokens=profile.max_output_tokens, deadline_ms=min(300_000, remaining_ms),
            metadata={"execution_context": execution_context.as_dict(),
                      "prepared_model_id": model_id, "prepared_context_sha256": invocation.context_sha256,
                      "task_plan_sha256": invocation.task_plan_sha256,
                      "model_attachment_sha256": attachment.attachment_sha256,
                      "profile_sha256": profile.profile_sha256},
        )
        authority = selected_policy.get("authority")
        if not isinstance(authority, Mapping):
            raise PermissionError("member execution policy has no native authority binding")
        request = ProviderRequest(
            invocation_id=invocation_id,
            correlation_id=(correlation_for(model_id) if correlation_for else execution_context.trace_root_id),
            project_id=project_id,
            adapter_id=str(getattr(adapter, "adapter_id", "")),
            model_id=adapter.artifact_sha256,
            actor_id=actor_id,
            accountable_owner=accountable_owner,
            payload=canonical.as_dict(),
            session_id=session_id,
            budget_id=adapter.budget_id,
            max_input_tokens=min(profile.context_tokens, attachment.context_tokens),
            max_output_tokens=profile.max_output_tokens,
            authority_revision=authority.get("revision"),
            task_plan_sha256=getattr(invocation, "task_plan_sha256", None),
            model_attachment_sha256=getattr(invocation.attachment, "attachment_sha256", None),
            model_revision=getattr(invocation.attachment, "model_revision", None),
            requested_egress="loopback",
            task_id=execution_context.root_execution_id,
        )
        if workflow_effect_receipt is not None:
            if any(value is None for value in (project_root,workflow_task_plan,workflow_agent_spec,workflow_placements)):
                raise PermissionError('local shared provider requires its exact signed workflow owner')
            from .remote_member_execution import execute_local_custodied_member
            return execute_local_custodied_member(root=project_root,gateway=gateway,binding=adapter,
                policy=selected_policy,invocation=invocation,context=execution_context,cancel_requested=cancellation_token,
                signed_task=workflow_effect_receipt,task_plan=workflow_task_plan,spec=workflow_agent_spec,placements=workflow_placements,
                invoke=lambda cancelled:execute_provider_request(gateway,selected_policy,request,adapter.adapter,
                    streaming=True,cancel_requested=cancelled,max_output_bytes=output_limit))
        try:
            value, _receipt = execute_provider_request(
                gateway, selected_policy, request, adapter.adapter, streaming=True,
                cancel_requested=cancellation_token, max_output_bytes=output_limit,
            )
            if cancellation_token is not None and cancellation_token():
                raise MemberExecutionUnavailable("member was cancelled before accepting the provider result")
            adapter.assert_current()
        except ProviderInvocationError:
            raise
        return value

    member_executor.__name__ = "provider_member_executor"
    return member_executor
