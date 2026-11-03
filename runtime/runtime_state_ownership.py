"""Fail-closed validation for the proposed runtime-state ownership registry.

The candidate registry is evidence and schema only. It is not an authorization
source, and this module is deliberately not wired into producer classification.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


MATRIX_SCHEMA_VERSION = "px.os-1067-runtime-state-ownership-matrix/1.0"
REGISTRY_SCHEMA_VERSION = "px.runtime-state-ownership-registry/1.0"
REGISTRY_STATE = "candidate_no_owner_approval"
RESOURCE_CLASS_ORDER = (
    "authoritative_durable",
    "regenerable_durable",
    "ephemeral_process_local",
    "shared_durable",
    "delegated_persistent",
)
RESOURCE_CLASSES = frozenset(RESOURCE_CLASS_ORDER)
EXISTING_AUTHORIZATION_CONTROLS = frozenset(
    {"effect_grant", "scope_lease", "effect_intent"}
)
_MATRIX_RESOURCE_FIELDS = frozenset(
    {
        "resource_id",
        "resource",
        "writers",
        "readers",
        "candidate_owner",
        "candidate_owner_evidence",
        "provenance",
        "retention",
        "lifecycle",
        "authorization",
        "unresolved_questions",
    }
)
_PRODUCER_FIELDS = frozenset(
    {"producer", "resource_ids", "disposition", "evidence"}
)
_RESOURCE_CANDIDATE_FIELD_ORDER = (
    "resource_id",
    "scope",
    "resource_class",
    "accountable_owner",
    "owner_approval_event_id",
    "provenance",
    "retention",
    "lifecycle",
    "concurrency",
    "authorization",
    "reclamation",
    "recovery",
)
_RESOURCE_CANDIDATE_FIELDS = frozenset(_RESOURCE_CANDIDATE_FIELD_ORDER)
_RECORD_AUTHORIZATION_FIELDS = frozenset(
    {
        "per_run_governed_authorization_required",
        "existing_controls",
        "standing_write_privilege",
        "registry_confers_write_authority",
        "registry_confers_deletion_authority",
    }
)
_EXPECTED_RECORD_CONTRACT = {
    "required_fields": list(_RESOURCE_CANDIDATE_FIELD_ORDER),
    "resource_classes": list(RESOURCE_CLASS_ORDER),
    "unresolved_owner_value": None,
    "approval_required_before_registration": True,
}
_EXPECTED_AUTHORIZATION_CONTRACT = {
    "per_run_governed_authorization_required": True,
    "existing_controls": ["effect_grant", "scope_lease", "effect_intent"],
    "standing_write_privilege": False,
    "registry_confers_write_authority": False,
    "registry_confers_deletion_authority": False,
}
_NO_RESOURCE_DISPOSITIONS = frozenset(
    {
        "non_filesystem_candidate",
        "read_only",
        "read_only_candidate",
        "stream_output",
        "network_stream_output",
        "process_local_session_cache_and_project_reads",
    }
)
_REQUIRED_REPRESENTATIVE_CASES = frozenset(
    {
        "authoritative_durable",
        "regenerable_durable",
        "ephemeral_process_local",
        "shared_state",
        "delegated_persistent_mutation",
    }
)


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object, *, allow_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty_text(item) for item in value)
    )


def _portable_scope(value: object) -> bool:
    if not _nonempty_text(value):
        return False
    scope = str(value)
    if "\\" in scope or ":" in scope or scope.startswith("/"):
        return False
    return all(part not in {"", ".", ".."} for part in scope.split("/"))


def validate_resource_candidate(record: object) -> list[str]:
    """Validate an unresolved record shape without accepting ownership authority."""
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["resource candidate must be an object"]

    if any(not isinstance(field, str) for field in record):
        return ["resource candidate field names must be strings"]
    actual_fields = set(record)
    missing = _RESOURCE_CANDIDATE_FIELDS - actual_fields
    extra = actual_fields - _RESOURCE_CANDIDATE_FIELDS
    if missing:
        errors.append(f"resource candidate is missing fields: {sorted(missing)}")
    if extra:
        errors.append(f"resource candidate has unknown fields: {sorted(extra)}")

    errors.extend(validate_resource_record_common(record))
    if record.get("accountable_owner") is not None:
        errors.append("candidate record may not assign an accountable owner")
    if record.get("owner_approval_event_id") is not None:
        errors.append("candidate record may not claim owner approval")
    return errors


def validate_approved_resource_record(
    record: object, *, group_members: Iterable[str] = ()
) -> list[str]:
    """Validate an APPROVED ownership record.

    Approval changes one thing: who is accountable. It does not change the authorization
    contract, so this reuses the same field and control checks. Two additional rules keep
    the ownership boundary honest:

    * an approved record must name an approval event;
    * the accountable owner may NOT be one of the resource group's own producers. A module
      cannot be the reconciling authority for state that it itself writes; allowing that
      would make "it writes there" a proof of ownership.
    """
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["approved resource record must be an object"]
    actual_fields = set(record)
    if actual_fields != _RESOURCE_CANDIDATE_FIELDS:
        missing = _RESOURCE_CANDIDATE_FIELDS - actual_fields
        extra = actual_fields - _RESOURCE_CANDIDATE_FIELDS
        if missing:
            errors.append(f"resource record is missing fields: {sorted(missing)}")
        if extra:
            errors.append(f"resource record has unknown fields: {sorted(extra)}")
        return errors

    errors.extend(validate_resource_record_common(record))
    owner = record.get("accountable_owner")
    if not _nonempty_text(owner):
        errors.append("an approved record must name an accountable owner")
    if not _nonempty_text(record.get("owner_approval_event_id")):
        errors.append("an approved record must cite the approval event")
    if _nonempty_text(owner):
        normalised_owner = str(owner).replace("\\", "/").strip("/")
        members = {
            str(member).replace("\\", "/").strip("/") for member in group_members
        }
        if normalised_owner in members:
            errors.append(
                "accountable owner may not be a producer of the resource it would own"
            )
    return errors


def validate_resource_record_common(record: Mapping[str, Any]) -> list[str]:
    """Field checks shared by candidate and approved records."""
    errors: list[str] = []
    if not _nonempty_text(record.get("resource_id")):
        errors.append("resource_id must be non-empty text")
    if not _portable_scope(record.get("scope")):
        errors.append("scope must be a portable repository-relative path")
    if record.get("resource_class") not in RESOURCE_CLASSES:
        errors.append("resource_class is not in the closed vocabulary")
    if not _string_list(record.get("provenance"), allow_empty=False):
        errors.append("provenance must be a non-empty array of evidence references")

    for field in ("retention", "lifecycle", "concurrency", "reclamation", "recovery"):
        if not _nonempty_text(record.get(field)):
            errors.append(f"{field} must be explicit or marked unresolved")

    authorization = record.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorization must be an object")
        return errors
    if set(authorization) != _RECORD_AUTHORIZATION_FIELDS:
        errors.append("authorization fields do not match the closed contract")
    if authorization.get("per_run_governed_authorization_required") is not True:
        errors.append("per-run governed authorization is required")
    controls = authorization.get("existing_controls")
    if (
        not isinstance(controls, list)
        or not controls
        or any(
            not isinstance(control, str)
            or control not in EXISTING_AUTHORIZATION_CONTROLS
            for control in controls
        )
        or len(controls) != len({control for control in controls if isinstance(control, str)})
    ):
        errors.append("existing_controls must name unique existing controls")
    for field in (
        "standing_write_privilege",
        "registry_confers_write_authority",
        "registry_confers_deletion_authority",
    ):
        if authorization.get(field) is not False:
            errors.append(f"{field} must be false")
    return errors


def validate_resource_authority_candidate(record: object) -> list[str]:
    """Legacy entry point retained for callers that validate an unresolved record."""
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["resource candidate must be an object"]
    return errors


def validate_matrix(matrix: object) -> dict[str, Any]:
    """Validate source-graph completeness and ensure it contains no owner decisions."""
    errors: list[str] = []
    if not isinstance(matrix, Mapping):
        return {"valid": False, "errors": ["matrix must be an object"]}
    if matrix.get("schema_version") != MATRIX_SCHEMA_VERSION:
        errors.append("unsupported matrix schema_version")

    baseline = matrix.get("baseline")
    expected_count = None
    if not isinstance(baseline, Mapping):
        errors.append("baseline must be an object")
    else:
        expected_count = baseline.get("runtime_producers")
        if type(expected_count) is not int or expected_count != 68:
            errors.append("baseline runtime_producers must equal the admitted 68-producer census")

    resources = matrix.get("resources")
    if not isinstance(resources, list):
        errors.append("resources must be an array")
        resources = []
    resource_ids: list[str] = []
    for index, resource in enumerate(resources):
        if not isinstance(resource, Mapping):
            errors.append(f"resources[{index}] must be an object")
            continue
        missing = _MATRIX_RESOURCE_FIELDS - set(resource)
        if missing:
            errors.append(f"resources[{index}] is missing fields: {sorted(missing)}")
        resource_id = resource.get("resource_id")
        if not _nonempty_text(resource_id):
            errors.append(f"resources[{index}].resource_id must be non-empty text")
        else:
            resource_ids.append(str(resource_id))
        writers = resource.get("writers")
        for field in ("writers", "readers"):
            if not _string_list(resource.get(field), allow_empty=True):
                errors.append(f"{resource_id}: {field} must be an array of paths")
        candidates = resource.get("candidate_owner")
        if not isinstance(candidates, list) or not _string_list(
            candidates, allow_empty=True
        ):
            errors.append(
                f"{resource_id}: candidate_owner must be an unapproved component list"
            )
        else:
            for candidate in candidates:
                if (
                    not isinstance(candidate, str)
                    or not candidate.startswith("runtime/")
                ):
                    errors.append(
                        f"{resource_id}: candidate owner candidates must be runtime paths"
                    )
                elif isinstance(writers, list) and candidate not in writers:
                    errors.append(
                        f"{resource_id}: candidate owners must be verified writer components"
                    )
        if not _string_list(resource.get("provenance"), allow_empty=False):
            errors.append(f"{resource_id}: provenance must cite source evidence")
        if not _string_list(resource.get("unresolved_questions"), allow_empty=False):
            errors.append(f"{resource_id}: unresolved_questions must be non-empty")
        for field in (
            "resource",
            "candidate_owner_evidence",
            "retention",
            "lifecycle",
            "authorization",
        ):
            if not _nonempty_text(resource.get(field)):
                errors.append(f"{resource_id}: {field} must be explicit")
    if len(resource_ids) != len(set(resource_ids)):
        errors.append("resource_id values must be unique")
    known_resource_ids = set(resource_ids)

    producers = matrix.get("producer_dispositions")
    if not isinstance(producers, list):
        errors.append("producer_dispositions must be an array")
        producers = []
    producer_paths: list[str] = []
    referenced_resource_ids: set[str] = set()
    unmapped_paths: set[str] = set()
    for index, producer in enumerate(producers):
        if not isinstance(producer, Mapping):
            errors.append(f"producer_dispositions[{index}] must be an object")
            continue
        missing = _PRODUCER_FIELDS - set(producer)
        if missing:
            errors.append(f"producer_dispositions[{index}] is missing fields: {sorted(missing)}")
        path = producer.get("producer")
        if not _nonempty_text(path) or not str(path).startswith("runtime/"):
            errors.append(f"producer_dispositions[{index}].producer must be a runtime path")
        else:
            producer_paths.append(str(path))
        if not _string_list(producer.get("resource_ids"), allow_empty=True):
            errors.append(f"{path}: resource_ids must be an array")
            continue
        resource_refs = set(producer["resource_ids"])
        if len(resource_refs) != len(producer["resource_ids"]):
            errors.append(f"{path}: resource_ids must be unique")
        unknown = resource_refs - known_resource_ids
        if unknown:
            errors.append(f"{path}: unknown resources {sorted(unknown)}")
        referenced_resource_ids.update(resource_refs)
        if not resource_refs:
            unmapped_paths.add(str(path))
            if producer.get("disposition") not in _NO_RESOURCE_DISPOSITIONS:
                errors.append(f"{path}: unresolved effect must have a resource group")
        if not _nonempty_text(producer.get("disposition")):
            errors.append(f"{path}: disposition must be non-empty")
        if not _nonempty_text(producer.get("evidence")):
            errors.append(f"{path}: evidence must be non-empty")

    if len(producer_paths) != len(set(producer_paths)):
        errors.append("producer paths must be unique")
    if expected_count is not None and len(producer_paths) != expected_count:
        errors.append("producer disposition count does not match the baseline census")
    declared_unmapped = matrix.get("producers_without_local_durable_resource")
    if not isinstance(declared_unmapped, list) or not _string_list(
        declared_unmapped, allow_empty=False
    ):
        errors.append("producers_without_local_durable_resource must be a non-empty array")
    elif set(declared_unmapped) != unmapped_paths:
        errors.append("unmapped producer list does not match producer dispositions")
    if known_resource_ids != referenced_resource_ids:
        errors.append(
            "every resource group must be referenced by at least one producer disposition"
        )

    representative = matrix.get("representative_validation_cases")
    if not isinstance(representative, Mapping):
        errors.append("representative_validation_cases must be an object")
    else:
        if set(representative) != _REQUIRED_REPRESENTATIVE_CASES:
            errors.append("representative validation classes do not match the required set")
        if any(value not in known_resource_ids for value in representative.values()):
            errors.append("representative validation case references an unknown resource")

    return {
        "valid": not errors,
        "errors": errors,
        "producer_count": len(producer_paths),
        "resource_count": len(resource_ids),
        "unmapped_producer_count": len(unmapped_paths),
    }


def validate_candidate_registry(
    document: object, matrix: object
) -> dict[str, Any]:
    """Validate the proposed registry and require every resource to remain unresolved."""
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return {"valid": False, "errors": ["registry must be an object"]}

    required_fields = {
        "schema_version",
        "registry_state",
        "matrix",
        "resources",
        "unresolved_resource_ids",
        "record_contract",
        "authorization_contract",
        "notes",
    }
    if set(document) != required_fields:
        errors.append("registry fields do not match the closed candidate schema")
    if document.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        errors.append("unsupported registry schema_version")
    if document.get("registry_state") != REGISTRY_STATE:
        errors.append("registry must remain candidate_no_owner_approval")
    if document.get("matrix") != "px-os-1067-runtime-state-ownership-matrix.json":
        errors.append("registry matrix reference is not canonical")
    records = document.get("resources")
    if records != []:
        errors.append("candidate registry may not contain owner registrations")
    if document.get("record_contract") != _EXPECTED_RECORD_CONTRACT:
        errors.append("record_contract does not match the deterministic contract")
    if document.get("authorization_contract") != _EXPECTED_AUTHORIZATION_CONTRACT:
        errors.append("authorization_contract may not create standing or deletion authority")
    notes = document.get("notes")
    if not _string_list(notes, allow_empty=False):
        errors.append("notes must document candidate status and authority boundaries")

    matrix_report = validate_matrix(matrix)
    errors.extend(f"matrix: {error}" for error in matrix_report["errors"])
    matrix_ids: list[str] = []
    if isinstance(matrix, Mapping) and isinstance(matrix.get("resources"), list):
        matrix_ids = [
            str(resource["resource_id"])
            for resource in matrix["resources"]
            if isinstance(resource, Mapping) and _nonempty_text(resource.get("resource_id"))
        ]
    unresolved = document.get("unresolved_resource_ids")
    if not isinstance(unresolved, list) or not _string_list(
        unresolved, allow_empty=False
    ):
        errors.append("unresolved_resource_ids must be a non-empty array")
        unresolved = []
    elif len(unresolved) != len(set(unresolved)):
        errors.append("unresolved_resource_ids must be unique")
    if list(unresolved) != matrix_ids:
        errors.append("unresolved_resource_ids must exactly follow the matrix resource order")

    return {
        "valid": not errors,
        "errors": errors,
        "unresolved_resource_ids": list(unresolved),
        "producer_count": matrix_report["producer_count"],
        "resource_count": matrix_report["resource_count"],
        "unmapped_producer_count": matrix_report["unmapped_producer_count"],
    }
