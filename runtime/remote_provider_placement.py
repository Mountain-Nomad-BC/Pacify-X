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


def require_complete_group_provider_custody(task_plan, *, project_root):
    """Preflight every local shared writer through its current signed native owner."""
    from .model_group_preparation import member_execution_input
    from .remote_member_execution import _current_local_identity
    plan=task_plan.as_dict() if hasattr(task_plan,'as_dict') else task_plan
    members=plan.get('model_group_preparation',{}).get('members',[])
    if any(row['attachment'].get('schema_version') == REMOTE_ATTACHMENT_SCHEMA for row in members):
        for row in members:
            if row['attachment'].get('schema_version') != REMOTE_ATTACHMENT_SCHEMA:
                _current_local_identity(project_root,member_execution_input(plan,row))
