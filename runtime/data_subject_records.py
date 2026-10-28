"""Authenticated subject resolution for preserved canonical MemoryVault records.

Subject bindings are explicit owner assertions, never inferred from memory IDs.
The native host returns an access/export image; it does not write an unmanaged
export copy. Sealed vault history cannot be erased through this owner.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from .archive_io import portable_member_name, reject_path_links
from .json_io import bounded_canonical_json_bytes, load_json_object
from .memory_vault import MemoryVault
from .studio_authority import StudioAuthorityStore

SCHEMA = "px.subject-record-request/1.0"
OPERATIONS = {"subject-access", "subject-export", "subject-erase", "subject-retention"}
CONTROL_ROOT = ".agentic_engineering_os_px/runtime-core/data-controls"


def _digest(value):
    return hashlib.sha256(bounded_canonical_json_bytes(value, max_bytes=4 * 1024 * 1024)).hexdigest()


def _relative(value):
    if type(value) is not str:
        raise ValueError("exact project-relative locator required")
    return portable_member_name(value, allow_directory=False, max_bytes=512)


def _approved(authority, root, locator, schema):
    locator = _relative(locator)
    if not locator.startswith(CONTROL_ROOT + "/"):
        raise PermissionError("subject binding/policy must use canonical control owner")
    path = root / locator
    reject_path_links(path)
    value = authority.verify_receipt(load_json_object(path, max_bytes=256 * 1024))
    if value.get("schema_version") != schema or value.get("state") != "approved":
        raise PermissionError("current approved subject binding/policy required")
    if not value.get("approved_by") or not value.get("evidence_refs"):
        raise PermissionError("subject binding/policy lacks owner approval evidence")
    expiry = datetime.fromisoformat(str(value.get("expires_utc", "")).replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise PermissionError("subject binding/policy expired")
    return value


def _consume_request_approval(authority, request):
    from .data_controls import validate_control_descriptor
    validate_control_descriptor()
    payload = {key: value for key, value in request.items() if key != "approval_capability"}
    approval = authority.consume_host_operation_approval(request["approval_capability"],
        kind="data-controls", operation=request["operation"], supplied_payload=payload)
    if approval["approved_by"] != request["requester_id"]:
        raise PermissionError("authenticated host actor differs from data requester")
    return approval


def subject_record_request(project_root: Path, request: dict) -> dict:
    """Normal native host consumer with real grants, policy and vault validation."""
    fields = {"schema_version", "operation", "requester_id", "subject_id", "grant_id",
              "binding_locator", "policy_locator", "approval_capability"}
    if type(request) is not dict or set(request) != fields or any(
            type(request[k]) is not str or not request[k] for k in fields - {"approval_capability"}):
        raise ValueError("closed bounded subject record request required")
    bounded_canonical_json_bytes(request, max_bytes=256 * 1024)
    operation = request["operation"]
    if request["schema_version"] != SCHEMA or operation not in OPERATIONS:
        raise ValueError("unsupported subject record operation")
    root = Path(project_root)
    reject_path_links(root)
    root = root.resolve(strict=True)
    binding_locator, policy_locator = (_relative(request[k]) for k in
                                      ("binding_locator", "policy_locator"))
    # Resolve existing host authority only. Missing authority never creates keys.
    authority = StudioAuthorityStore.open_existing(root)
    binding = _approved(authority, root, binding_locator, "px.subject-record-binding/1.0")
    policy = _approved(authority, root, policy_locator, "px.data-control-policy/1.0")
    if binding.get("subject_id") != request["subject_id"] or binding.get("owner") != "runtime.memory_vault":
        raise PermissionError("explicit subject/canonical owner binding differs")
    if (policy.get("owner") != "runtime.memory_vault" or
            policy.get("policy_id") != binding.get("policy_id") or
            policy.get("subject_id") != request["subject_id"] or
            operation not in policy.get("allowed_operations", []) or
            request["requester_id"] not in policy.get("authorized_requesters", [])):
        raise PermissionError("approved policy does not authorize this subject/requester/operation")
    grant, grant_digest = authority.resolve_grant(request["grant_id"],
        subject_id=request["requester_id"], required_effects=("read", "write"))
    if not any(".agentic_engineering_os_px/studios/authority" == _relative(scope) or
            ".agentic_engineering_os_px/studios/authority".startswith(_relative(scope) + "/")
            for scope in grant["scope_roots"]):
        raise PermissionError("native grant omits approval consumption custody")
    _consume_request_approval(authority, request)
    vault_relative = _relative(binding.get("vault_relative"))
    if not any(vault_relative == _relative(scope) or vault_relative.startswith(_relative(scope) + "/")
               for scope in grant["scope_roots"]):
        raise PermissionError("native grant does not cover canonical vault")
    vault_root = root / vault_relative
    reject_path_links(vault_root)
    vault = MemoryVault(vault_root, workspace_id=binding["workspace_id"], project_id=binding["project_id"])
    identifiers = binding.get("memory_ids")
    if (type(identifiers) is not list or not identifiers or len(identifiers) > 128 or
            any(type(item) is not str or not item or len(item) > 256 for item in identifiers) or
            len(set(identifiers)) != len(identifiers)):
        raise ValueError("bounded explicit canonical record identities required")
    from .file_lock import FileLock
    with FileLock(vault_root / ".memory-control" / "vault.lock"):
        # Validate every revision and lifecycle before releasing any selected content.
        from .bounded_walk import bounded_walk, WalkLimits
        for entry in bounded_walk(vault_root, limits=WalkLimits(max_files=10000, max_bytes=64*1024*1024,
                max_entries=20000, max_directories=10000, max_duration_seconds=30)).entries:
            reject_path_links(entry.path)
        records = vault.records()
        selected = [item for item in records if item.memory_id in identifiers]
        if {item.memory_id for item in selected} != set(identifiers) or any(
                item.workspace_id != binding["workspace_id"] or item.project_id != binding["project_id"]
                for item in selected):
            raise ValueError("binding references missing or mismatched canonical records")
        from dataclasses import asdict
        from .memory_vault import _json_default
        import json
        image = json.loads(json.dumps([asdict(item) for item in selected], default=_json_default))
        image_digest = _digest(image)
        if binding.get("record_image_sha256") != image_digest:
            raise PermissionError("subject binding is stale against actual canonical revisions")
        # Recheck live approval/grant/admission at the release boundary.
        if binding != _approved(authority, root, binding_locator, "px.subject-record-binding/1.0") or \
                policy != _approved(authority, root, policy_locator, "px.data-control-policy/1.0"):
            raise PermissionError("subject authority changed during resolution")
        _, current_grant_digest = authority.resolve_grant(request["grant_id"],
            subject_id=request["requester_id"], required_effects=("read", "write"))
        if current_grant_digest != grant_digest:
            raise PermissionError("native subject grant changed")
        preserved = operation in {"subject-erase", "subject-retention"}
        result = {"schema_version": "px.subject-record-response/1.0", "operation": operation,
            "subject_id": request["subject_id"], "owner": "runtime.memory_vault",
            "record_count": len(selected), "record_image_sha256": image_digest,
            "binding_sha256": _digest(binding), "policy_sha256": _digest(policy),
            "grant_sha256": grant_digest, "subject_resolution": "explicit_owner_binding",
            "records": [] if preserved else image,
            "record_content_exported": operation == "subject-export",
            "status": "PRESERVED_SEALED_HISTORY_ERASURE_REFUSED" if preserved else "RESOLVED",
            "erased_count": 0, "effects_executed": not preserved,
            "coverage_complete": False, "legal_signoff_asserted": False,
            "residual_surfaces": ["sealed canonical revisions and lifecycle", "vault Markdown notes",
                "index generations", "external backups/exports", "provider-side copies"]}
        bounded_canonical_json_bytes(result, max_bytes=4 * 1024 * 1024)
        return result
