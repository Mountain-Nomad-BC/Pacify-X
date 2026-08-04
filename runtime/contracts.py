"""Dependency-free JSON-Schema boundary checks for shipped contracts.

The implementation intentionally supports the exact Draft 2020-12 keyword
surface used by this package. Unknown validation keywords fail corpus
certification instead of being silently ignored.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .paths import declared_file_available


SUPPORTED_DIALECT = "https://json-schema.org/draft/2020-12/schema"
MAX_REF_DEPTH = 64
SUPPORTED_FORMATS = {"date", "date-time", "uri"}
ANNOTATION_KEYS = {"$schema", "$id", "$defs", "title", "description", "default"}
VALIDATION_KEYS = {
    "$ref", "type", "const", "enum", "required", "properties",
    "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
    "minLength", "pattern", "minimum", "maximum", "multipleOf", "format",
    "allOf", "anyOf", "not", "if", "then",
}

_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_RFC3339_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_URN = re.compile(r"^urn:[A-Za-z0-9][A-Za-z0-9-]{0,31}:[^\s:][^\s]*$")


class ContractValidationError(ValueError):
    """Raised when an instance does not satisfy a shipped contract."""


def _load(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-JSON numeric constant {value!r} in {path}")

    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError(f"schema must be an object: {path}")
    return data


def _contract_root_for(schema_path: Path, contract_root: Path | None) -> Path:
    if contract_root is not None:
        return contract_root.resolve(strict=True)
    resolved_path = schema_path.resolve(strict=True)
    for parent in (resolved_path.parent, *resolved_path.parents):
        if parent.name == "contracts":
            return parent
    return resolved_path.parent


def _resolve_pointer(document: dict[str, Any], fragment: str, ref: str, schema_path: Path) -> dict[str, Any]:
    if not fragment:
        return document
    if not fragment.startswith("/"):
        raise ValueError(f"unsupported JSON Schema reference fragment {ref!r} in {schema_path}")
    target: Any = document
    for raw_part in fragment[1:].split("/"):
        part = unquote(raw_part).replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise ValueError(f"unresolved reference {ref!r} in {schema_path}")
        target = target[part]
    if not isinstance(target, dict):
        raise ValueError(f"reference does not resolve to a schema object: {ref!r}")
    return target


def _resolve_external_path(ref_path: str, schema_path: Path, contract_root: Path) -> Path:
    decoded = unquote(ref_path)
    if not decoded:
        raise ValueError(f"external reference has no path in {schema_path}")
    if Path(decoded).is_absolute() or PurePosixPath(decoded).is_absolute() or PureWindowsPath(decoded).is_absolute():
        raise ValueError(f"absolute schema reference is not allowed: {ref_path!r}")
    if Path(decoded).suffix.lower() != ".json":
        raise ValueError(f"referenced schema must be a JSON file: {ref_path!r}")

    lexical_root = Path(os.path.abspath(str(contract_root)))
    lexical_target = Path(os.path.abspath(str(schema_path.parent / decoded)))
    root_key = os.path.normcase(str(lexical_root))
    target_key = os.path.normcase(str(lexical_target))
    try:
        contained = os.path.commonpath((root_key, target_key)) == root_key
    except ValueError:
        contained = False
    if not contained:
        raise ValueError(f"schema reference escapes contract root: {ref_path!r}")
    relative = Path(os.path.relpath(lexical_target, lexical_root))

    cursor = lexical_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError(f"symlinked schema references are not allowed: {ref_path!r}")

    try:
        target_path = lexical_target.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"unresolved external schema reference {ref_path!r} in {schema_path}") from exc
    if not target_path.is_file():
        raise ValueError(f"referenced schema is not a file: {ref_path!r}")
    return target_path


def _resolve_ref(
    ref: str,
    schema: dict[str, Any],
    schema_path: Path,
    contract_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"schema reference must be a non-empty string in {schema_path}")
    parsed = urlsplit(ref)
    if parsed.scheme or parsed.netloc or parsed.query:
        raise ValueError(f"URI schema references are not allowed: {ref!r}")

    ref_path, marker, fragment = ref.partition("#")
    if not ref_path:
        target_path = schema_path.resolve(strict=True)
        target_document = schema
    else:
        target_path = _resolve_external_path(ref_path, schema_path, contract_root)
        target_document = _load(target_path)
    target = _resolve_pointer(target_document, fragment if marker else "", ref, schema_path)
    key = f"{target_path.as_posix()}#{fragment if marker else ''}"
    return target, target_document, target_path, key


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _valid_datetime(value: str) -> bool:
    if _RFC3339_DATETIME.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_date(value: str) -> bool:
    if _RFC3339_DATE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_uri(value: str) -> bool:
    if not value or any(character.isspace() or ord(character) < 0x20 for character in value) or "\\" in value:
        return False
    parsed = urlsplit(value)
    if _URI_SCHEME.fullmatch(parsed.scheme) is None:
        return False
    scheme = parsed.scheme.lower()
    if scheme == "urn":
        return _URN.fullmatch(value) is not None
    if scheme not in {"http", "https"}:
        return False
    if not parsed.netloc or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        return False
    try:
        parsed.port
    except ValueError:
        return False
    return True


def _is_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": _finite_number(value),
        "null": value is None,
    }.get(expected, False)


def _errors(
    instance: Any,
    rule: dict[str, Any],
    root_schema: dict[str, Any],
    schema_path: Path,
    at: str,
    contract_root: Path,
    ref_stack: tuple[str, ...] = (),
) -> list[str]:
    errors: list[str] = []
    if "$ref" in rule:
        resolved, resolved_document, resolved_path, key = _resolve_ref(
            rule["$ref"], root_schema, schema_path, contract_root
        )
        if key in ref_stack:
            return [f"{at}: schema reference cycle detected at {key}"]
        if len(ref_stack) >= MAX_REF_DEPTH:
            return [f"{at}: schema reference depth exceeds {MAX_REF_DEPTH}"]
        errors.extend(
            _errors(
                instance,
                resolved,
                resolved_document,
                resolved_path,
                at,
                contract_root,
                ref_stack + (key,),
            )
        )
        siblings = {key_name: value for key_name, value in rule.items() if key_name != "$ref"}
        if siblings:
            errors.extend(_errors(instance, siblings, root_schema, schema_path, at, contract_root, ref_stack))
        return errors
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
                errors.extend(_errors(value, child, root_schema, schema_path, f"{at}/{key}", contract_root, ref_stack))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{at}: unexpected property {key}")
            elif isinstance(rule.get("additionalProperties"), dict):
                errors.extend(
                    _errors(
                        value,
                        rule["additionalProperties"],
                        root_schema,
                        schema_path,
                        f"{at}/{key}",
                        contract_root,
                        ref_stack,
                    )
                )
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
                errors.extend(
                    _errors(value, rule["items"], root_schema, schema_path, f"{at}/{index}", contract_root, ref_stack)
                )
    if isinstance(instance, str):
        if len(instance) < int(rule.get("minLength", 0)):
            errors.append(f"{at}: string is too short")
        if "pattern" in rule and re.search(str(rule["pattern"]), instance) is None:
            errors.append(f"{at}: string does not match required pattern")
        if "format" in rule:
            declared_format = rule.get("format")
            valid = {
                "date-time": _valid_datetime,
                "date": _valid_date,
                "uri": _valid_uri,
            }.get(declared_format)
            if valid is None:
                errors.append(f"{at}: unsupported format {declared_format}")
            elif not valid(instance):
                errors.append(f"{at}: invalid {declared_format}")
    if isinstance(instance, float) and not math.isfinite(instance):
        errors.append(f"{at}: non-finite numbers are not valid JSON numbers")
    elif _finite_number(instance):
        if "minimum" in rule and instance < rule["minimum"]:
            errors.append(f"{at}: value is below minimum")
        if "maximum" in rule and instance > rule["maximum"]:
            errors.append(f"{at}: value is above maximum")
        if "multipleOf" in rule:
            try:
                if Decimal(str(instance)) % Decimal(str(rule["multipleOf"])) != 0:
                    errors.append(f"{at}: value is not a required multiple")
            except (InvalidOperation, ZeroDivisionError):
                errors.append(f"{at}: invalid multipleOf schema constraint")
    for child in rule.get("allOf", ()):
        errors.extend(_errors(instance, child, root_schema, schema_path, at, contract_root, ref_stack))
    if "anyOf" in rule and not any(
        not _errors(instance, child, root_schema, schema_path, at, contract_root, ref_stack)
        for child in rule["anyOf"]
    ):
        errors.append(f"{at}: no anyOf branch matched")
    if "not" in rule and not _errors(instance, rule["not"], root_schema, schema_path, at, contract_root, ref_stack):
        errors.append(f"{at}: prohibited schema matched")
    if (
        "if" in rule
        and not _errors(instance, rule["if"], root_schema, schema_path, at, contract_root, ref_stack)
        and "then" in rule
    ):
        errors.extend(_errors(instance, rule["then"], root_schema, schema_path, at, contract_root, ref_stack))
    return errors


def validate_instance(instance: Any, schema_path: Path, *, contract_root: Path | None = None) -> None:
    schema_path = schema_path.resolve(strict=True)
    resolved_contract_root = _contract_root_for(schema_path, contract_root)
    schema = _load(schema_path)
    _admit_schema(schema, schema_path, resolved_contract_root)
    errors = _errors(instance, schema, schema, schema_path, "$", resolved_contract_root)
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


def _minimal(
    rule: dict[str, Any],
    root_schema: dict[str, Any],
    schema_path: Path,
    contract_root: Path,
    ref_stack: tuple[str, ...] = (),
) -> Any:
    if "$ref" in rule:
        resolved, resolved_document, resolved_path, key = _resolve_ref(
            rule["$ref"], root_schema, schema_path, contract_root
        )
        if key in ref_stack:
            raise ValueError(f"schema reference cycle detected at {key}")
        if len(ref_stack) >= MAX_REF_DEPTH:
            raise ValueError(f"schema reference depth exceeds {MAX_REF_DEPTH}")
        candidate = _minimal(
            resolved,
            resolved_document,
            resolved_path,
            contract_root,
            ref_stack + (key,),
        )
        siblings = {key_name: value for key_name, value in rule.items() if key_name != "$ref"}
        if siblings and _errors(candidate, siblings, root_schema, schema_path, "$", contract_root, ref_stack):
            sibling_candidate = _minimal(siblings, root_schema, schema_path, contract_root, ref_stack)
            if not _errors(
                sibling_candidate,
                resolved,
                resolved_document,
                resolved_path,
                "$",
                contract_root,
                ref_stack + (key,),
            ):
                candidate = sibling_candidate
        return candidate
    if "const" in rule:
        return rule["const"]
    if "enum" in rule and rule["enum"]:
        return rule["enum"][0]
    if "default" in rule:
        return rule["default"]
    if "anyOf" in rule:
        return _minimal(rule["anyOf"][0], root_schema, schema_path, contract_root, ref_stack)
    declared = rule.get("type")
    choices = [declared] if isinstance(declared, str) else list(declared or ())
    selected = next((item for item in choices if item != "null"), choices[0] if choices else "object")
    if selected == "object":
        value: dict[str, Any] = {}
        properties = rule.get("properties", {})
        for key in rule.get("required", ()):
            value[key] = _minimal(properties.get(key, {}), root_schema, schema_path, contract_root, ref_stack)
        for child in rule.get("allOf", ()):
            if "if" in child:
                if not _errors(value, child["if"], root_schema, schema_path, "$", contract_root, ref_stack) and "then" in child:
                    then = child["then"]
                    for key in then.get("required", ()):
                        value[key] = _minimal(
                            properties.get(key, {}), root_schema, schema_path, contract_root, ref_stack
                        )
                continue
            addition = _minimal(child, root_schema, schema_path, contract_root, ref_stack)
            if isinstance(addition, dict):
                value.update(addition)
        if (
            "if" in rule
            and not _errors(value, rule["if"], root_schema, schema_path, "$", contract_root, ref_stack)
            and "then" in rule
        ):
            addition = _minimal(rule["then"], root_schema, schema_path, contract_root, ref_stack)
            if isinstance(addition, dict):
                value.update(addition)
        return value
    if selected == "array":
        count = int(rule.get("minItems", 0))
        return [
            _minimal(rule.get("items", {}), root_schema, schema_path, contract_root, ref_stack)
            for _ in range(count)
        ]
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


def build_minimal_instance(schema_path: Path, *, contract_root: Path | None = None) -> Any:
    """Build a deterministic contract smoke fixture; validation remains authoritative."""
    schema_path = schema_path.resolve(strict=True)
    resolved_contract_root = _contract_root_for(schema_path, contract_root)
    schema = _load(schema_path)
    _admit_schema(schema, schema_path, resolved_contract_root)
    return _minimal(schema, schema, schema_path, resolved_contract_root)


def _schema_structure_errors(value: Any, at: str = "$", *, schema_object: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{at}: schema rule must be an object"] if schema_object else errors
    if schema_object:
        unknown = set(value) - ANNOTATION_KEYS - VALIDATION_KEYS
        errors.extend(f"{at}: unsupported schema keyword {key}" for key in sorted(unknown))
        if "$ref" in value and (not isinstance(value["$ref"], str) or not value["$ref"]):
            errors.append(f"{at}: $ref must be a non-empty string")
        if "$schema" in value and not isinstance(value["$schema"], str):
            errors.append(f"{at}: $schema must be a string")
        if "$id" in value and not isinstance(value["$id"], str):
            errors.append(f"{at}: $id must be a string")
        if "type" in value:
            declared = value["type"]
            choices = [declared] if isinstance(declared, str) else declared
            known_types = {"object", "array", "string", "boolean", "integer", "number", "null"}
            if (
                not isinstance(choices, list)
                or not choices
                or not all(isinstance(item, str) and item in known_types for item in choices)
            ):
                errors.append(f"{at}: type must declare one or more supported JSON types")
        if "enum" in value and not isinstance(value["enum"], list):
            errors.append(f"{at}: enum must be a list")
        if "required" in value and (not isinstance(value["required"], list) or not all(isinstance(item, str) for item in value["required"])):
            errors.append(f"{at}: required must be a string list")
        if "properties" in value and not isinstance(value["properties"], dict):
            errors.append(f"{at}: properties must be an object")
        if "additionalProperties" in value and not isinstance(value["additionalProperties"], (bool, dict)):
            errors.append(f"{at}: additionalProperties must be a boolean or schema object")
        for key in ("minItems", "maxItems", "minLength"):
            if key in value and (
                not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 0
            ):
                errors.append(f"{at}: {key} must be a non-negative integer")
        if "uniqueItems" in value and not isinstance(value["uniqueItems"], bool):
            errors.append(f"{at}: uniqueItems must be a boolean")
        for key in ("minimum", "maximum", "multipleOf"):
            if key in value and not _finite_number(value[key]):
                errors.append(f"{at}: {key} must be a finite JSON number")
        if "multipleOf" in value and _finite_number(value["multipleOf"]) and value["multipleOf"] <= 0:
            errors.append(f"{at}: multipleOf must be greater than zero")
        if (
            _finite_number(value.get("minimum"))
            and _finite_number(value.get("maximum"))
            and value["minimum"] > value["maximum"]
        ):
            errors.append(f"{at}: minimum must not exceed maximum")
        if "pattern" in value:
            if not isinstance(value["pattern"], str):
                errors.append(f"{at}: pattern must be a string")
            else:
                try:
                    re.compile(value["pattern"])
                except re.error:
                    errors.append(f"{at}: pattern must be a valid regular expression")
        if "format" in value and (
            not isinstance(value["format"], str) or value["format"] not in SUPPORTED_FORMATS
        ):
            errors.append(f"{at}: unsupported format {value['format']!r}")
        if "then" in value and "if" not in value:
            errors.append(f"{at}: then without if is unsupported")
        for map_key in ("properties", "$defs"):
            child_map = value.get(map_key, {})
            if child_map and not isinstance(child_map, dict):
                errors.append(f"{at}: {map_key} must be an object")
            elif isinstance(child_map, dict):
                for key, child in child_map.items():
                    errors.extend(_schema_structure_errors(child, f"{at}/{map_key}/{key}"))
        for key in ("items", "not", "if", "then"):
            child = value.get(key)
            if key in value and not isinstance(child, dict):
                errors.append(f"{at}: {key} must be a schema object")
            elif isinstance(child, dict):
                errors.extend(_schema_structure_errors(child, f"{at}/{key}"))
        child = value.get("additionalProperties")
        if isinstance(child, dict):
            errors.extend(_schema_structure_errors(child, f"{at}/additionalProperties"))
        for key in ("allOf", "anyOf"):
            children = value.get(key, ())
            if key in value and not isinstance(children, list):
                errors.append(f"{at}: {key} must be a list")
            elif isinstance(children, list):
                for index, child in enumerate(children):
                    errors.extend(_schema_structure_errors(child, f"{at}/{key}/{index}"))
    return errors


def _schema_children(rule: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for map_key in ("properties", "$defs"):
        child_map = rule.get(map_key)
        if isinstance(child_map, dict):
            yield from (child for child in child_map.values() if isinstance(child, dict))
    for key in ("items", "additionalProperties", "not", "if", "then"):
        child = rule.get(key)
        if isinstance(child, dict):
            yield child
    for key in ("allOf", "anyOf"):
        children = rule.get(key)
        if isinstance(children, list):
            yield from (child for child in children if isinstance(child, dict))


def _admit_schema(schema: dict[str, Any], schema_path: Path, contract_root: Path) -> set[Path]:
    dependencies = {schema_path.resolve(strict=True)}
    validated_documents: set[Path] = set()

    def validate_document(document: dict[str, Any], document_path: Path) -> None:
        if document_path in validated_documents:
            return
        document_errors = _schema_structure_errors(document)
        if document.get("$schema") != SUPPORTED_DIALECT:
            document_errors.append(f"$: schema dialect must be {SUPPORTED_DIALECT}")
        if document_errors:
            raise ValueError("schema admission failed: " + "; ".join(document_errors))
        validated_documents.add(document_path)

    def walk(
        rule: dict[str, Any],
        document: dict[str, Any],
        document_path: Path,
        ref_stack: tuple[str, ...],
    ) -> None:
        if "$ref" in rule:
            resolved, resolved_document, resolved_path, key = _resolve_ref(
                rule["$ref"], document, document_path, contract_root
            )
            if key in ref_stack:
                chain = " -> ".join((*ref_stack, key))
                raise ValueError(f"schema reference cycle detected: {chain}")
            if len(ref_stack) >= MAX_REF_DEPTH:
                raise ValueError(f"schema reference depth exceeds {MAX_REF_DEPTH}")
            dependencies.add(resolved_path)
            validate_document(resolved_document, resolved_path)
            walk(resolved, resolved_document, resolved_path, ref_stack + (key,))
        for child in _schema_children(rule):
            walk(child, document, document_path, ref_stack)

    schema_path = schema_path.resolve(strict=True)
    validate_document(schema, schema_path)
    walk(schema, schema, schema_path, ())
    return dependencies


def contract_digest(schema_path: Path, *, contract_root: Path | None = None) -> str:
    """Digest a contract and every schema document reached through its references."""
    schema_path = schema_path.resolve(strict=True)
    resolved_contract_root = _contract_root_for(schema_path, contract_root)
    schema = _load(schema_path)
    dependencies = _admit_schema(schema, schema_path, resolved_contract_root)
    records = []
    for dependency in sorted(dependencies, key=lambda item: item.as_posix()):
        records.append(
            {
                "path": dependency.relative_to(resolved_contract_root).as_posix(),
                "sha256": hashlib.sha256(dependency.read_bytes()).hexdigest(),
            }
        )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_contract_corpus(root: Path) -> dict[str, Any]:
    contract_root = root / "contracts"
    ownership = _load(root / "registry" / "contract_ownership.json")
    ownership_records = ownership.get("records", ())
    ownership_by_path = {str(item.get("path")): item for item in ownership_records if isinstance(item, dict)}
    paths = sorted(path.relative_to(root).as_posix() for path in contract_root.rglob("*.json"))
    errors: list[str] = []
    owned: dict[str, str] = {}
    contract_digests: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        schema: dict[str, Any] = {}
        try:
            schema = _load(path)
            errors.extend(f"{relative}: {item}" for item in _schema_structure_errors(schema))
            if schema.get("$schema") != SUPPORTED_DIALECT:
                errors.append(f"{relative}: missing Draft 2020-12 declaration")
            expected_id = f"urn:engineering-loop-bootstrap:contract:{relative.removeprefix('contracts/').removesuffix('.schema.json').replace('/', ':')}"
            if schema.get("$id") != expected_id:
                errors.append(f"{relative}: unstable or missing contract id")
            _admit_schema(schema, path, contract_root.resolve(strict=True))
            contract_digests[relative] = contract_digest(path, contract_root=contract_root)
            example = build_minimal_instance(path, contract_root=contract_root)
            example_errors = _errors(example, schema, schema, path, "$", contract_root.resolve(strict=True))
            errors.extend(f"{relative}: generated valid fixture failed: {item}" for item in example_errors)
            if schema.get("required") and not _errors(
                {}, schema, schema, path, "$", contract_root.resolve(strict=True)
            ):
                errors.append(f"{relative}: empty-object negative fixture unexpectedly passed")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"{relative}: {error}")
        ownership_record = ownership_by_path.get(relative)
        if ownership_record is None:
            errors.append(f"{relative}: missing explicit ownership record")
        else:
            owner = str(ownership_record.get("owner", ""))
            if not owner or not declared_file_available(root, owner):
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
                if not declared_file_available(root, str(producer)):
                    errors.append(f"{relative}: missing producer {producer}")
            for test in ownership_record.get("tests", ()):
                if not declared_file_available(root, str(test)):
                    errors.append(f"{relative}: missing ownership test {test}")
    extras = sorted(set(ownership_by_path) - set(paths))
    errors.extend(f"ownership record references missing contract: {relative}" for relative in extras)
    if ownership.get("contract_count") != len(paths):
        errors.append("contract ownership count does not match corpus")
    enforcement_counts: dict[str, int] = {}
    for record in ownership_records:
        state = str(record.get("enforcement", "missing")); enforcement_counts[state] = enforcement_counts.get(state, 0) + 1
    corpus_bytes = json.dumps(contract_digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "valid": not errors,
        "contract_count": len(paths),
        "owned_count": len(owned),
        "enforcement_counts": enforcement_counts,
        "contract_corpus_digest": hashlib.sha256(corpus_bytes).hexdigest(),
        "contract_digests": contract_digests,
        "errors": errors,
    }
