"""Native data inventory/planning and authenticated canonical record controls.

Planning operations grant no authority. Actual subject controls resolve existing
native signed policy, grant and payload-bound host approval through canonical
owners. No software operation invents policy or asserts legal approval.
"""
from __future__ import annotations

from collections.abc import Mapping
import argparse
import hashlib
import json
from pathlib import Path
import sys

from .data_inventory import build_inventory, erasure_plan, retention_report
from .json_io import bounded_canonical_json_bytes, decode_json_object, load_json_object

SCHEMA_VERSION = "px.data-control-request/1.0"
MAX_REQUEST_BYTES = 256 * 1024
OPERATIONS = {
    "inventory": {"schema_version", "operation", "retention_policy"},
    "erasure-plan": {"schema_version", "operation", "retention_policy", "subject_scope"},
    "retention-report": {"schema_version", "operation", "retention_policy", "now_utc", "store_last_updated_utc"},
    "access-manifest": {"schema_version", "operation", "retention_policy", "subject_scope"},
}


def validate_control_descriptor() -> dict:
    from .data_subject_records import OPERATIONS as vault_operations, SCHEMA as vault_schema
    from .personal_record_store import OPERATIONS as personal_operations, SCHEMA as personal_schema
    from .archive_io import reject_path_links
    locator = Path(__file__).with_name("data_control_contracts.json")
    reject_path_links(locator)
    descriptor = load_json_object(locator, max_bytes=64 * 1024)
    expected = {"runtime.data_subject_records": (vault_operations, vault_schema),
                "runtime.personal_record_store": (personal_operations, personal_schema)}
    if descriptor.get("schema_version") != "px.data-control-owner-contract/1.0" or set(descriptor.get("owners", {})) != set(expected):
        raise PermissionError("native data-control approval descriptor differs")
    for owner, (operations, schema) in expected.items():
        row = descriptor["owners"][owner]
        if (type(row.get("operations")) is not list or set(row["operations"]) != operations or
                len(row["operations"]) != len(operations) or row.get("schema_version") != schema):
            raise PermissionError("native data-control approval descriptor scope differs")
    return descriptor


def describe_existing_approval(project_root: Path) -> dict:
    from .studio_authority import StudioAuthorityStore
    from .archive_io import reject_path_links
    validate_control_descriptor()
    authority = StudioAuthorityStore.open_existing(project_root.resolve(strict=True))
    locator = authority.approval_verifier_path
    reject_path_links(locator)
    verifier = load_json_object(locator, max_bytes=64 * 1024)
    public = verifier.get("public_key_jwk")
    from .studio_models import canonical_bytes
    if (verifier.get("schema_version") != "px.studio-host-approval-verifier/2.0" or
            verifier.get("project_identity") != authority.project_identity or
            verifier.get("host_surface") != "vscode-extension-host" or
            verifier.get("approved_by") != "human:vscode-local-user" or type(public) is not dict or
            verifier.get("key_id") != hashlib.sha256(canonical_bytes(public)).hexdigest()):
        raise PermissionError("existing data-control host approval verifier required")
    return {"schema_version": "px.data-control-existing-host/1.0", "project_identity": authority.project_identity,
            "key_root": str(authority.key_root), "record_path": str(locator), "key_id": verifier["key_id"]}


def data_control_request(project_root: Path, request: Mapping) -> dict:
    """Resolve normal host requests through the single native inventory owner."""
    if type(request) is not dict:
        raise ValueError("data control request must be an object")
    if request.get("operation") in {"personal-create", "personal-access", "personal-export", "personal-erase", "personal-retention", "personal-use", "personal-rectify", "personal-withdraw-consent"}:
        from .personal_record_store import personal_record_request
        return personal_record_request(project_root, request)
    if request.get("operation") in {"subject-access", "subject-export", "subject-erase", "subject-retention"}:
        from .data_subject_records import subject_record_request
        return subject_record_request(project_root, request)
    bounded_canonical_json_bytes(request, max_bytes=MAX_REQUEST_BYTES)
    operation = request.get("operation")
    if (request.get("schema_version") != SCHEMA_VERSION or type(operation) is not str
            or operation not in OPERATIONS or set(request) - OPERATIONS[operation]
            or not {"schema_version", "operation"} <= set(request)):
        raise ValueError("unsupported or nonclosed data control request")
    policy = request.get("retention_policy")
    if policy is not None and type(policy) is not dict:
        raise ValueError("retention policy planning input must be an object")
    inventory = build_inventory(project_root, retention_policy=policy)
    if operation == "inventory":
        result = inventory
    elif operation == "retention-report":
        if type(request.get("now_utc")) is not str:
            raise ValueError("retention report requires an explicit evidenced time")
        stamps = request.get("store_last_updated_utc", {})
        if type(stamps) is not dict or any(type(value) is not str for value in stamps.values()):
            raise ValueError("owner-supplied timestamp references must be an object of strings")
        result = retention_report(inventory, request["now_utc"], store_last_updated_utc=stamps)
    else:
        scope = request.get("subject_scope")
        if type(scope) is not list:
            raise ValueError("scoped data planning requires an explicit subject identifier array")
        plan = erasure_plan(inventory, scope)
        if operation == "erasure-plan":
            result = plan
        else:
            result = {
                "schema_version": "px.data-access-manifest/1.0",
                "inventory_sha256": inventory["inventory_sha256"],
                "subject_scope": plan["subject_scope"],
                "candidate_store_owners": [{"store_id": row["store_id"], "owner": row["owner"],
                    "relative_root": row["relative_root"], "data_class": row["data_class"]}
                    for row in inventory["stores"] if row["present"]],
                "status": "CANONICAL_SUBJECT_RECORD_RESOLUTION_REQUIRED",
                "record_count": None,
                "record_content_exported": False,
                "coverage_complete": False,
                "unenumerated_surfaces": inventory["unenumerated_surfaces"],
                "authority_granted": False,
            }
    response = {"schema_version": "px.data-control-response/1.0", "operation": operation,
                "request_sha256": hashlib.sha256(bounded_canonical_json_bytes(
                    request, max_bytes=MAX_REQUEST_BYTES)).hexdigest(),
                "result": result, "effects_executed": False, "authority_granted": False,
                "legal_signoff_asserted": False}
    bounded_canonical_json_bytes(response, max_bytes=4 * 1024 * 1024)
    return response


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Native data planning and authenticated subject controls")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--describe-existing-approval", action="store_true")
    args = parser.parse_args(argv)
    if args.describe_existing_approval:
        print(json.dumps(describe_existing_approval(args.project_root), sort_keys=True))
        return 0
    image = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    request = decode_json_object(image, max_bytes=MAX_REQUEST_BYTES,
                                 max_depth=24, max_nodes=50000)
    result = data_control_request(args.project_root, request)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
