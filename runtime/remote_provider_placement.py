"""Explicit remote service placement; provider budget owns quota, never fake CPU capacity."""
from pathlib import Path
from .execution_placement import _hash
from .remote_model_attachment import RemoteModelAttachment,validate_remote_model_attachment,remote_model_attachment_from_dict,SCHEMA as REMOTE_ATTACHMENT_SCHEMA

SCHEMA="px.governed-remote-provider-placement/1.0"


def route_remote_provider(task_plan,*,project_root,model_id=None):
    from .task_execution_plan import validate_task_execution_plan
    from .model_group_preparation import member_attachment
    if not validate_task_execution_plan(task_plan)["valid"]:
        raise ValueError("remote placement requires an intact prepared task plan")
    attachment,member=member_attachment(task_plan,model_id)
    if member is None or attachment.get("schema_version")!=REMOTE_ATTACHMENT_SCHEMA:
        raise ValueError("remote placement requires one exact prepared remote member")
    typed=remote_model_attachment_from_dict(attachment)
    if type(typed) is not RemoteModelAttachment or not validate_remote_model_attachment(typed,root=Path(project_root))["valid"]:
        raise ValueError("remote placement requires a current native remote attachment")
    record={"schema_version":SCHEMA,"selected_backend":"remote_provider",
        "task_plan_sha256":task_plan["plan_sha256"],"model_attachment_sha256":typed.attachment_sha256,
        "model_id":typed.model_id,"context_sha256":member["context_sha256"],
        "provider_id":typed.provider_id,"adapter_id":typed.adapter_id,"profile_id":typed.profile_id,"profile_sha256":typed.profile_sha256,
        "origin":typed.origin,"reservation_owner":"runtime.provider_gateway"}
    return {**record,"placement_sha256":_hash(record)}


def validate_remote_provider_placement(placement,task_plan,*,project_root):
    if type(placement) is not dict or placement.get("schema_version")!=SCHEMA:
        raise ValueError("exact native remote placement required")
    expected=route_remote_provider(task_plan,project_root=project_root,model_id=placement.get("model_id"))
    if placement!=expected:
        raise ValueError("remote placement service/origin/plan binding differs")
    return expected


def require_complete_group_provider_custody(task_plan, *, project_root, adapter_for=None):
    """Preflight every local shared writer through its current signed native owner.

    A local member writes shared provider state, so it needs the same custody
    proof whether or not a remote member happens to sit beside it. Nesting this
    behind an "any remote member" guard let a local-only group run with no
    custody check at all.

    The proof is taken from the binding that will actually execute the member
    (``adapter_for``), not from a second global resolver read: the configured
    host policy need not be loadable during an admitted execution whose exact
    adapters are already resolved, and re-resolving here would demand host state
    the caller has already replaced with a bound provider.
    """
    from .model_group_preparation import member_execution_input
    from .task_execution_plan import task_execution_plan_from_dict
    plan=task_plan.as_dict() if hasattr(task_plan,'as_dict') else task_plan
    # The canonical parser accepts both the typed plan and its exact JSON form.
    typed=task_execution_plan_from_dict(plan)
    prepared=typed.model_group_preparation
    members=(prepared.as_dict() if hasattr(prepared,'as_dict') else prepared or {}).get('members',[])
    local = [row for row in members if row['attachment'].get('schema_version') != REMOTE_ATTACHMENT_SCHEMA]
    if not local:
        return
    from .remote_member_execution import _local_identity
    for row in local:
        invocation=member_execution_input(plan,row)
        if adapter_for is None:
            # The executor was supplied without a bound resolver, so the caller
            # owns provider admission (the executor refuses an unadmitted
            # member itself). Demanding host configuration here would fail
            # executions that are already fully bound, which is why this is not
            # treated as a custody proof.
            continue
        binding=adapter_for(invocation.model_id)
        if binding is None:
            raise PermissionError("local group member has no admitted provider binding")
        # The binding owns its policy; assert_current() is the native custody
        # proof that this is the provider actually running now.
        policy=getattr(binding,'policy',None)
        if policy is None:
            raise PermissionError("local group member binding has no native execution policy")
        binding.assert_current()
        _local_identity(binding,policy,invocation)
