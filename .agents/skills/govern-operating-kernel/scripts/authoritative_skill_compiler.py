#!/usr/bin/env python3
"""Compile a bounded authoritative skill contract; fail closed on YAML ambiguity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


MAX_BYTES = 64 * 1024
MAX_LINES = 512
MAX_DEPTH = 12
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
UNSAFE_YAML = re.compile(r"(?<!\S)[&*!][A-Za-z0-9_-]+")


class ContractParseError(ValueError):
    """Raised when the bounded YAML contract grammar is violated."""


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        raise ContractParseError("empty scalar is ambiguous")
    if UNSAFE_YAML.search(value) or value.startswith(("|", ">")):
        raise ContractParseError("aliases, anchors, tags, and block scalars are unsupported")
    if value.startswith(('"', "'")):
        if len(value) < 2 or value[-1] != value[0]:
            raise ContractParseError("unterminated quoted scalar")
        return json.loads(value) if value[0] == '"' else value[1:-1].replace("''", "'")
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ContractParseError(f"flow collections must be valid JSON: {error}") from error
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        return float(value) if "." in value else int(value)
    return value


def _lines(path: Path) -> list[tuple[int, str, int]]:
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ContractParseError("contract exceeds the 64 KiB limit")
    text = data.decode("utf-8")
    if "\t" in text or "\x00" in text:
        raise ContractParseError("tabs and NUL bytes are forbidden")
    result: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ContractParseError(f"line {number}: indentation must use two-space steps")
        result.append((indent, raw.lstrip(), number))
    if len(result) > MAX_LINES:
        raise ContractParseError("contract exceeds the line limit")
    return result


def _parse_block(lines: list[tuple[int, str, int]], index: int, indent: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise ContractParseError("contract exceeds the nesting-depth limit")
    if index >= len(lines) or lines[index][0] != indent:
        raise ContractParseError("missing nested value")
    sequence = lines[index][1].startswith("- ")
    container: Any = [] if sequence else {}
    while index < len(lines):
        current_indent, content, number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ContractParseError(f"line {number}: unexpected indentation")
        if sequence:
            if not content.startswith("- "):
                raise ContractParseError(f"line {number}: cannot mix sequence and mapping entries")
            item = content[2:].strip()
            if not item:
                value, index = _parse_block(lines, index + 1, indent + 2, depth + 1)
                container.append(value)
                continue
            container.append(_scalar(item))
            index += 1
            continue
        if content.startswith("- ") or ":" not in content:
            raise ContractParseError(f"line {number}: expected key: value mapping")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        if not KEY.fullmatch(key):
            raise ContractParseError(f"line {number}: invalid mapping key")
        if key in container:
            raise ContractParseError(f"line {number}: duplicate key {key!r}")
        raw_value = raw_value.strip()
        if raw_value:
            container[key] = _scalar(raw_value)
            index += 1
        else:
            container[key], index = _parse_block(lines, index + 1, indent + 2, depth + 1)
    return container, index


def parse_bounded_yaml(path: Path) -> dict[str, Any]:
    lines = _lines(path)
    if not lines:
        raise ContractParseError("contract is empty")
    value, index = _parse_block(lines, 0, 0, 0)
    if index != len(lines) or not isinstance(value, dict):
        raise ContractParseError("contract root must be one complete mapping")
    return value


def _validate(contract: dict[str, Any]) -> None:
    product_root = Path(__file__).resolve().parents[4]
    schema_path = product_root / "contracts/authoritative-skill-contract.schema.json"
    if not schema_path.is_file():
        raise RuntimeError("authoritative skill contract schema is missing")
    if str(product_root) not in sys.path:
        sys.path.insert(0, str(product_root))
    try:
        from runtime.contracts import validate_instance
    except ModuleNotFoundError:
        from engineering_bootstrap.contracts import validate_instance
    validate_instance(contract, schema_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = parse_bounded_yaml(args.contract)
        _validate(contract)
    except (ContractParseError, UnicodeDecodeError, OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "rejected", "error": type(error).__name__, "detail": str(error)}))
        return 2
    output = args.out
    output.mkdir(parents=True, exist_ok=False)
    registry = {key: contract.get(key) for key in ("id", "name", "summary", "category", "version", "security_class")}
    (output / "registry_entry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "permission_manifest.json").write_text(json.dumps(contract.get("permissions", {}), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "TEST_SKELETON.md").write_text(
        f"# {contract['name']} tests\n\n- preconditions\n- postconditions\n- invariants\n- permission denials\n- failure recovery\n- evidence contract\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "compiled", "id": contract["id"], "outputs": sorted(path.name for path in output.iterdir())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
