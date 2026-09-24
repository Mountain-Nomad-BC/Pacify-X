"""Plan-only action fusion for already-admitted sequential actions."""
from __future__ import annotations
import hashlib, json, re
from typing import Mapping, Sequence

SCHEMA_VERSION = "px.action-fusion-plan/1.0"
ALLOWED_FOLLOWUP_KINDS = frozenset({"syntax_check", "focused_test", "build", "lint"})
_SHA = re.compile(r"^[0-9a-f]{64}$")

def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def build_fused_action_plan(*, mutation_binding_id: str, mutation_payload_sha256: str, mutation_effect_grant_ids: Sequence[str], followup_binding_id: str, followup_kind: str, followup_arguments: Mapping[str, object], followup_effect_grant_ids: Sequence[str], requires_inspection_before_followup: bool, approval_required_between_actions: bool, rollback_binding_id: str | None = None) -> dict[str, object]:
    if type(requires_inspection_before_followup) is not bool or type(approval_required_between_actions) is not bool:
        raise ValueError("fusion boundary flags must be booleans")
    if followup_kind not in ALLOWED_FOLLOWUP_KINDS: raise ValueError("follow-up kind is not fusion-eligible")
    if requires_inspection_before_followup: raise PermissionError("inspection boundary cannot be fused")
    if approval_required_between_actions: raise PermissionError("approval boundary cannot be fused")
    if not mutation_binding_id.strip() or not followup_binding_id.strip() or mutation_binding_id == followup_binding_id:
        raise ValueError("fusion requires distinct admitted bindings")
    if not _SHA.fullmatch(mutation_payload_sha256): raise ValueError("mutation payload SHA is invalid")
    mutation_grants = sorted(set(map(str, mutation_effect_grant_ids))); followup_grants = sorted(set(map(str, followup_effect_grant_ids)))
    if not mutation_grants or not followup_grants or any(not item.strip() or len(item) > 256 for item in mutation_grants + followup_grants):
        raise PermissionError("each fused action requires valid existing effect grants")
    if rollback_binding_id is not None and (type(rollback_binding_id) is not str or not rollback_binding_id.strip() or len(rollback_binding_id) > 256):
        raise ValueError("rollback binding identity is invalid")
    rendered_arguments = json.dumps(dict(followup_arguments), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(rendered_arguments) > 65536:
        raise ValueError("follow-up arguments exceed fusion plan budget")
    body = {"schema_version": SCHEMA_VERSION, "mutation_binding_id": mutation_binding_id, "mutation_payload_sha256": mutation_payload_sha256, "mutation_effect_grant_ids": mutation_grants, "followup_binding_id": followup_binding_id, "followup_kind": followup_kind, "followup_arguments": dict(followup_arguments), "followup_effect_grant_ids": followup_grants, "rollback_binding_id": rollback_binding_id, "requires_distinct_receipts": True, "stop_followup_if_mutation_fails": True, "authority_granted": False}
    return {**body, "plan_sha256": _hash(body)}

def validate_fusion_plan(plan: Mapping[str, object]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("authority_granted") is not False or plan.get("requires_distinct_receipts") is not True or plan.get("stop_followup_if_mutation_fails") is not True:
        raise ValueError("fusion plan contract is invalid")
    body = {str(k): v for k, v in plan.items() if k != "plan_sha256"}
    if plan.get("plan_sha256") != _hash(body): raise ValueError("fusion plan hash mismatch")

def record_fusion_outcome(plan: Mapping[str, object], *, mutation_receipt_sha256: str, mutation_succeeded: bool, followup_receipt_sha256: str | None = None, followup_succeeded: bool | None = None, rollback_receipt_sha256: str | None = None) -> dict[str, object]:
    validate_fusion_plan(plan)
    if type(mutation_succeeded) is not bool: raise ValueError("mutation outcome must be boolean")
    if not _SHA.fullmatch(mutation_receipt_sha256): raise ValueError("mutation receipt is invalid")
    if not mutation_succeeded and followup_receipt_sha256 is not None: raise ValueError("follow-up cannot execute after failed mutation")
    if mutation_succeeded:
        if not _SHA.fullmatch(str(followup_receipt_sha256 or "")) or type(followup_succeeded) is not bool: raise ValueError("successful mutation requires a distinct follow-up receipt/outcome")
        if followup_receipt_sha256 == mutation_receipt_sha256: raise ValueError("fused actions require distinct receipts")
    if rollback_receipt_sha256 is not None and not _SHA.fullmatch(rollback_receipt_sha256): raise ValueError("rollback receipt is invalid")
    body = {"schema_version":"px.action-fusion-outcome/1.0", "plan_sha256":plan["plan_sha256"], "mutation_receipt_sha256":mutation_receipt_sha256, "mutation_succeeded":mutation_succeeded, "followup_receipt_sha256":followup_receipt_sha256, "followup_succeeded":followup_succeeded, "rollback_receipt_sha256":rollback_receipt_sha256, "completed": bool(mutation_succeeded and followup_succeeded), "authority_granted":False}
    return {**body, "outcome_sha256": _hash(body)}
