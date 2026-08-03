"""Dependency-free JSON-Schema boundary checks for shipped contracts.

The implementation intentionally supports the exact Draft 2020-12 keyword
surface used by this package. Unknown validation keywords fail corpus
certification instead of being silently ignored.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


ANNOTATION_KEYS = {"$schema", "$id", "$defs", "title", "description", "default"}
VALIDATION_KEYS = {
    "$ref", "type", "const", "enum", "required", "properties",
    "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
    "minLength", "pattern", "minimum", "maximum", "multipleOf", "format",
    "allOf", "anyOf", "not", "if", "then",
}


class ContractValidationError(ValueError):
    """Raised when an instance does not satisfy a shipped contract."""


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"schema must be an object: {path}")
    return data


def _resolve_ref(ref: str, schema: dict[str, Any], schema_path: Path) -> tuple[dict[str, Any], Path]:
    if ref.startswith("#/"):
        target: Any = schema
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return target, schema_path
    target_path = (schema_path.parent / ref).resolve()
    return _load(target_path), target_path


def _is_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _errors(instance: Any, rule: dict[str, Any], root_schema: dict[str, Any], schema_path: Path, at: str) -> list[str]:
    if "$ref" in rule:
        resolved, resolved_path = _resolve_ref(str(rule["$ref"]), root_schema, schema_path)
        return _errors(instance, resolved, root_schema if resolved_path == schema_path else resolved, resolved_path, at)
    errors: list[str] = []
    expected = rule.get("type")
    if expected is not None:
        choices = [expected] if isinstance(expected, str) else expected
        if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
            return [f"{at}: schema type declaration is invalid"]
        if not any(_is_type(instance, item) for item in choices):
            return [f"{at}: expected {' or '.join(choices)}"]
    if "const" in rule and instance != rule["const"]:
        errors.append(f"{at}: value does not equal required constant")
    if "enum" in rule and instance not in rule["enum"]:
        errors.append(f"{at}: value is outside the allowed enumeration")
    if isinstance(instance, dict):
        required = rule.get("required", ())
        for key in required:
            if key not in instance:
                errors.append(f"{at}: missing required property {key}")
        properties = rule.get("properties", {})
        if not isinstance(properties, dict):
            errors.append(f"{at}: schema properties must be an object")
            properties = {}
        for key, value in instance.items():
            child = properties.get(key)
            if isinstance(child, dict):
                errors.extend(_errors(value, child, root_schema, schema_path, f"{at}/{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{at}: unexpected property {key}")
            elif isinstance(rule.get("additionalProperties"), dict):
                errors.extend(_errors(value, rule["additionalProperties"], root_schema, schema_path, f"{at}/{key}"))
    if isinstance(instance, list):
        if len(instance) < int(rule.get("minItems", 0)):
            errors.append(f"{at}: too few items")
        if "maxItems" in rule and len(instance) > int(rule["maxItems"]):
            errors.append(f"{at}: too many items")
        if rule.get("uniqueItems") is True:
            encoded = [json.dumps(value, sort_keys=True, separators=(",", ":")) for value in instance]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{at}: items are not unique")
        if isinstance(rule.get("items"), dict):
            for index, value in enumerate(instance):
                errors.extend(_errors(value, rule["items"], root_schema, schema_path, f"{at}/{index}"))
    if isinstance(instance, str):
        if len(instance) < int(rule.get("minLength", 0)):
            errors.append(f"{at}: string is too short")
        if "pattern" in rule and re.search(str(rule["pattern"]), instance) is None:
            errors.append(f"{at}: string does not match required pattern")
        if "format" in rule:
            declared_format = rule.get("format")
            try:
                if declared_format == "date-time":
                    datetime.fromisoformat(instance.replace("Z", "+00:00"))
                elif declared_format == "date":
                    date.fromisoformat(instance)
                elif declared_format == "uri":
                    if not urlparse(instance).scheme:
                        raise ValueError("URI has no scheme")
                else:
                    errors.append(f"{at}: unsupported format {declared_format}")
            except ValueError:
                errors.append(f"{at}: invalid {declared_format}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in rule and instance < rule["minimum"]:
            errors.append(f"{at}: value is below minimum")
        if "maximum" in rule and instance > rule["maximum"]:
            errors.append(f"{at}: value is above maximum")
        if "multipleOf" in rule and abs((instance / rule["multipleOf"]) - round(instance / rule["multipleOf"])) > 1e-9:
            errors.append(f"{at}: value is not a required multiple")
    for child in rule.get("allOf", ()):
        errors.extend(_errors(instance, child, root_schema, schema_path, at))
    if "anyOf" in rule and not any(not _errors(instance, child, root_schema, schema_path, at) for child in rule["anyOf"]):
        errors.append(f"{at}: no anyOf branch matched")
    if "not" in rule and not _errors(instance, rule["not"], root_schema, schema_path, at):
        errors.append(f"{at}: prohibited schema matched")
    if "if" in rule and not _errors(instance, rule["if"], root_schema, schema_path, at) and "then" in rule:
        errors.extend(_errors(instance, rule["then"], root_schema, schema_path, at))
    return errors


def validate_instance(instance: Any, schema_path: Path) -> None:
    schema_path = schema_path.resolve()
    schema = _load(schema_path)
    errors = _errors(instance, schema, schema, schema_path, "$")
    if errors:
        raise ContractValidationError("; ".join(errors))


def _pattern_example(pattern: str) -> str:
    if pattern == "^sha256:[a-f0-9]{64}$":
        return "sha256:" + "a" * 64
    if pattern == "^evidence/bundles/[A-Za-z0-9._/-]+\\.json$":
        return "evidence/bundles/example/manifest.json"
    if "64}" in pattern:
        return "a" * 64
    if pattern in {"^[0-9]+\\.[0-9]+\\.[0-9]+$", "^\\d+\\.\\d+\\.\\d+$"}:
        return "1.0.0"
    if pattern == "^[A-P]+$":
        return "A"
    if ":" in pattern and "a-zA-Z_" in pattern:
        return "runtime.module:handler"
    prefixes = {
        "^agt_": "agt_example", "^cap_": "cap_example", "^dec_": "dec_example",
        "^evd_": "evd_example", "^int_": "int_example", "^prj_": "prj_example",
        "^qtn_": "qtn_example", "^repo_": "repo_example", "^ses_": "ses_example",
        "^skl_": "skl_example", "^ws_": "ws_example", "^wsp_": "wsp_example",
        "^xfer_": "xfer_example", "^project/prj_": "project/prj_example",
        "^projects/[^/]+/PROJECT_MANAGEMENT.md$": "projects/example/PROJECT_MANAGEMENT.md",
        "^projects/[^/]+$": "projects/example", "^projects/": "projects/example",
        "^projects_tracking/projects/prj_[^/]+/memory$": "projects_tracking/projects/prj_example/memory",
        "^projects_tracking/projects/prj_[^/]+$": "projects_tracking/projects/prj_example",
        "^projects_tracking/projects/prj_": "projects_tracking/projects/prj_example",
        "^projects_tracking/projects/": "projects_tracking/projects/prj_example",
    }
    for prefix, example in prefixes.items():
        if pattern.startswith(prefix):
            return example
    return "example"


def _minimal(rule: dict[str, Any], root_schema: dict[str, Any], schema_path: Path) -> Any:
    if "$ref" in rule:
        resolved, resolved_path = _resolve_ref(str(rule["$ref"]), root_schema, schema_path)
        return _minimal(resolved, root_schema if resolved_path == schema_path else resolved, resolved_path)
    if "const" in rule:
        return rule["const"]
    if "enum" in rule and rule["enum"]:
        return rule["enum"][0]
    if "default" in rule:
        return rule["default"]
    if "anyOf" in rule:
        return _minimal(rule["anyOf"][0], root_schema, schema_path)
    declared = rule.get("type")
    choices = [declared] if isinstance(declared, str) else list(declared or ())
    selected = next((item for item in choices if item != "null"), choices[0] if choices else "object")
    if selected == "object":
        value: dict[str, Any] = {}
        properties = rule.get("properties", {})
        for key in rule.get("required", ()):
            value[key] = _minimal(properties.get(key, {}), root_schema, schema_path)
        for child in rule.get("allOf", ()):
            if "if" in child:
                if not _errors(value, child["if"], root_schema, schema_path, "$") and "then" in child:
                    then = child["then"]
                    for key in then.get("required", ()):
                        value[key] = _minimal(properties.get(key, {}), root_schema, schema_path)
                continue
            addition = _minimal(child, root_schema, schema_path)
            if isinstance(addition, dict):
                value.update(addition)
        if "if" in rule and not _errors(value, rule["if"], root_schema, schema_path, "$") and "then" in rule:
            addition = _minimal(rule["then"], root_schema, schema_path)
            if isinstance(addition, dict):
                value.update(addition)
        return value
    if selected == "array":
        count = int(rule.get("minItems", 0))
        return [_minimal(rule.get("items", {}), root_schema, schema_path) for _ in range(count)]
    if selected == "string":
        if rule.get("format") == "date-time":
            return "2026-08-02T00:00:00Z"
        if rule.get("format") == "date":
            return "2026-08-02"
        if rule.get("format") == "uri":
            return "urn:example:value"
        result = _pattern_example(str(rule["pattern"])) if "pattern" in rule else "value"
        minimum = int(rule.get("minLength", 0))
        return result if len(result) >= minimum else result + "x" * (minimum - len(result))
    if selected == "integer":
        value = int(rule.get("minimum", 0))
        multiple = int(rule.get("multipleOf", 1))
        return ((value + multiple - 1) // multiple) * multiple
    if selected == "number":
        return float(rule.get("minimum", 0))
    if selected == "boolean":
        return False
    return None


def build_minimal_instance(schema_path: Path) -> Any:
    """Build a deterministic contract smoke fixture; validation remains authoritative."""
    schema_path = schema_path.resolve()
    schema = _load(schema_path)
    return _minimal(schema, schema, schema_path)


def _schema_structure_errors(value: Any, at: str = "$", *, schema_object: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{at}: schema rule must be an object"] if schema_object else errors
    if schema_object:
        unknown = set(value) - ANNOTATION_KEYS - VALIDATION_KEYS
        errors.extend(f"{at}: unsupported schema keyword {key}" for key in sorted(unknown))
        if "required" in value and (not isinstance(value["required"], list) or not all(isinstance(item, str) for item in value["required"])):
            errors.append(f"{at}: required must be a string list")
        if "properties" in value and not isinstance(value["properties"], dict):
            errors.append(f"{at}: properties must be an object")
        for map_key in ("properties", "$defs"):
            child_map = value.get(map_key, {})
            if child_map and not isinstance(child_map, dict):
                errors.append(f"{at}: {map_key} must be an object")
            elif isinstance(child_map, dict):
                for key, child in child_map.items():
                    errors.extend(_schema_structure_errors(child, f"{at}/{map_key}/{key}"))
        for key in ("items", "additionalProperties", "not", "if", "then"):
            child = value.get(key)
            if isinstance(child, dict):
                errors.extend(_schema_structure_errors(child, f"{at}/{key}"))
        for key in ("allOf", "anyOf"):
            children = value.get(key, ())
            if key in value and not isinstance(children, list):
                errors.append(f"{at}: {key} must be a list")
            elif isinstance(children, list):
                for index, child in enumerate(children):
                    errors.extend(_schema_structure_errors(child, f"{at}/{key}/{index}"))
    return errors


def validate_contract_corpus(root: Path) -> dict[str, Any]:
    contract_root = root / "contracts"
    ownership = _load(root / "registry" / "contract_ownership.json")
    ownership_records = ownership.get("records", ())
    ownership_by_path = {str(item.get("path")): item for item in ownership_records if isinstance(item, dict)}
    paths = sorted(path.relative_to(root).as_posix() for path in contract_root.rglob("*.json"))
    errors: list[str] = []
    owned: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        try:
            schema = _load(path)
            errors.extend(f"{relative}: {item}" for item in _schema_structure_errors(schema))
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                errors.append(f"{relative}: missing Draft 2020-12 declaration")
            expected_id = f"urn:engineering-loop-bootstrap:contract:{relative.removeprefix('contracts/').removesuffix('.schema.json').replace('/', ':')}"
            if schema.get("$id") != expected_id:
                errors.append(f"{relative}: unstable or missing contract id")
            # Resolve every local reference now, not when a future user discovers it.
            def refs(node: Any) -> None:
                if isinstance(node, dict):
                    if "$ref" in node:
                        _resolve_ref(str(node["$ref"]), schema, path)
                    for child in node.values(): refs(child)
                elif isinstance(node, list):
                    for child in node: refs(child)
            refs(schema)
            example = build_minimal_instance(path)
            example_errors = _errors(example, schema, schema, path, "$")
            errors.extend(f"{relative}: generated valid fixture failed: {item}" for item in example_errors)
            if schema.get("required") and not _errors({}, schema, schema, path, "$"):
                errors.append(f"{relative}: empty-object negative fixture unexpectedly passed")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"{relative}: {error}")
        ownership_record = ownership_by_path.get(relative)
        if ownership_record is None:
            errors.append(f"{relative}: missing explicit ownership record")
        else:
            owner = str(ownership_record.get("owner", ""))
            if not owner or not (root / owner).is_file():
                errors.append(f"{relative}: missing runtime owner {owner}")
            owned[relative] = owner
            if ownership_record.get("packaged") is not True:
                errors.append(f"{relative}: shipped contract is not marked packaged")
            if not ownership_record.get("enforcement"):
                errors.append(f"{relative}: missing enforcement classification")
            if ownership_record.get("contract_id") != schema.get("$id"):
                errors.append(f"{relative}: ownership contract id mismatch")
            if ownership_record.get("contract_version") != "1.0.0":
                errors.append(f"{relative}: ownership contract version is missing or invalid")
            for producer in ownership_record.get("producers", ()):
                if not (root / str(producer)).exists():
                    errors.append(f"{relative}: missing producer {producer}")
            for test in ownership_record.get("tests", ()):
                if not (root / str(test)).is_file():
                    errors.append(f"{relative}: missing ownership test {test}")
    extras = sorted(set(ownership_by_path) - set(paths))
    errors.extend(f"ownership record references missing contract: {relative}" for relative in extras)
    if ownership.get("contract_count") != len(paths):
        errors.append("contract ownership count does not match corpus")
    enforcement_counts: dict[str, int] = {}
    for record in ownership_records:
        state = str(record.get("enforcement", "missing")); enforcement_counts[state] = enforcement_counts.get(state, 0) + 1
    return {"valid": not errors, "contract_count": len(paths), "owned_count": len(owned), "enforcement_counts": enforcement_counts, "errors": errors}
