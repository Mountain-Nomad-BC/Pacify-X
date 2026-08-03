"""Narrow typed field-mapping adapter proposals (PC-502)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .common import (
    BuilderError,
    DuplicateAssetError,
    GapNotProvenError,
    bounded_unique,
    proposal_envelope,
    require_field_name,
    require_identifier,
)


JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array", "null"})


@dataclass(frozen=True, slots=True)
class FieldContract:
    name: str
    value_type: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class TypeContract:
    name: str
    fields: tuple[FieldContract, ...]


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    adapter_id: str
    source: TypeContract
    target: TypeContract
    field_mapping: tuple[tuple[str, str], ...]
    source_references: tuple[str, ...]


def _validate_contract(contract: TypeContract, label: str) -> dict[str, FieldContract]:
    require_identifier(contract.name, f"{label}.name")
    fields = bounded_unique(contract.fields, f"{label}.fields", maximum=24)
    result: dict[str, FieldContract] = {}
    for field in fields:
        require_field_name(field.name, f"{label}.field")
        if field.value_type not in JSON_TYPES:
            raise BuilderError(f"{label}.{field.name} has unsupported type {field.value_type}")
        if field.name in result:
            raise BuilderError(f"duplicate {label} field: {field.name}")
        result[field.name] = field
    return result


def _validated_mapping(request: AdapterRequest) -> tuple[tuple[str, str], ...]:
    source_fields = _validate_contract(request.source, "source")
    target_fields = _validate_contract(request.target, "target")
    mappings = bounded_unique(request.field_mapping, "field_mapping", maximum=24)
    seen_targets: set[str] = set()
    for source_name, target_name in mappings:
        if source_name not in source_fields:
            raise BuilderError(f"mapping references unknown source field: {source_name}")
        if target_name not in target_fields:
            raise BuilderError(f"mapping references unknown target field: {target_name}")
        if target_name in seen_targets:
            raise BuilderError(f"target field is mapped more than once: {target_name}")
        seen_targets.add(target_name)
        if source_fields[source_name].value_type != target_fields[target_name].value_type:
            raise BuilderError(
                f"incompatible field types: {source_name} -> {target_name}"
            )
    missing = sorted(
        name for name, field in target_fields.items() if field.required and name not in seen_targets
    )
    if missing:
        raise BuilderError("required target fields are unmapped: " + ", ".join(missing))
    return tuple(sorted(mappings, key=lambda item: (item[1], item[0])))


def propose_adapter(
    request: AdapterRequest,
    registry_records: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    adapter_id = require_identifier(request.adapter_id, "adapter_id")
    for record in registry_records:
        if record.get("id") == adapter_id:
            raise DuplicateAssetError(f"adapter already exists: {adapter_id}")
        if (
            request.target.name in record.get("provides", ())
            and request.source.name in record.get("consumes", ())
        ):
            raise GapNotProvenError(f"registry adapter {record.get('id')} already transforms this contract")
    if request.source.name == request.target.name:
        raise GapNotProvenError("source and target contracts are already compatible")
    mapping = _validated_mapping(request)
    sources = bounded_unique(request.source_references, "source_references", maximum=8)
    body = {
        "adapter": {
            "id": adapter_id,
            "status": "candidate",
            "transforms_exactly_one_contract": True,
            "source_contract": _contract_payload(request.source),
            "target_contract": _contract_payload(request.target),
            "field_mapping": [
                {"from": source_name, "to": target_name}
                for source_name, target_name in mapping
            ],
            "implementation_kind": "field_mapping_only",
            "business_logic_allowed": False,
            "schema_validation": "strict",
            "source_references": sorted(sources),
            "unit_tests": ["valid mapping", "missing required input", "invalid input type", "unknown input field"],
        },
        "registry_candidate": {"id": adapter_id, "visible_as": "candidate"},
    }
    return proposal_envelope("adapter", adapter_id, body)


def _contract_payload(contract: TypeContract) -> dict[str, object]:
    return {
        "name": contract.name,
        "fields": [
            {"name": field.name, "type": field.value_type, "required": field.required}
            for field in sorted(contract.fields, key=lambda item: item.name)
        ],
    }


def _matches_type(value: object, declared: str) -> bool:
    if declared == "null":
        return value is None
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = {"string": str, "object": dict, "array": list}[declared]
    return isinstance(value, expected)


def transform(request: AdapterRequest, payload: Mapping[str, object]) -> dict[str, object]:
    """Execute only the generated adapter's narrow field mapping, with strict input checks."""
    mapping = _validated_mapping(request)
    source_fields = _validate_contract(request.source, "source")
    unknown = sorted(set(payload) - set(source_fields))
    if unknown:
        raise BuilderError("unknown input fields: " + ", ".join(unknown))
    missing = sorted(name for name, field in source_fields.items() if field.required and name not in payload)
    if missing:
        raise BuilderError("missing required input fields: " + ", ".join(missing))
    for name, value in payload.items():
        if not _matches_type(value, source_fields[name].value_type):
            raise BuilderError(f"invalid input type for {name}: expected {source_fields[name].value_type}")
    return {target: payload[source] for source, target in mapping if source in payload}
