"""Schema-validated, lazy integration handler registry."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractValidationError, validate_instance


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _import_target(target: str) -> Callable[..., Any]:
    module_name, separator, symbol = target.partition(":")
    if not separator:
        raise ValueError(f"integration target must use module:symbol: {target}")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if not module_name.startswith("engineering_bootstrap.") or error.name not in {
            "engineering_bootstrap",
            module_name,
        }:
            raise
        module = importlib.import_module(
            "runtime." + module_name.removeprefix("engineering_bootstrap.")
        )
    value = getattr(module, symbol, None)
    if not callable(value):
        raise ValueError(f"integration target is not callable: {target}")
    return value


def validate_integrations(root: Path, *, smoke: bool = False) -> dict[str, Any]:
    registry = _load(root / "registry" / "integrations.json")
    schema = root / "contracts" / "integration-contract.schema.json"
    errors: list[str] = []
    records = registry.get("integrations", ())
    seen: set[str] = set()
    for record in records:
        identifier = (
            str(record.get("id", "missing")) if isinstance(record, dict) else "invalid"
        )
        try:
            validate_instance(record, schema)
            if identifier in seen:
                raise ValueError(f"duplicate integration id: {identifier}")
            seen.add(identifier)
            handler = _import_target(str(record["handler"]))
            healthcheck = _import_target(str(record["healthcheck"]))
            if smoke and record.get("status") == "active":
                result = healthcheck()
                if not isinstance(result, dict) or result.get("valid") is not True:
                    raise ValueError(f"healthcheck failed: {result!r}")
            del handler
        except (
            ContractValidationError,
            ImportError,
            AttributeError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            errors.append(f"{identifier}: {error}")
    return {
        "valid": not errors,
        "loading_rule": registry.get("loading_rule"),
        "count": len(records),
        "active_count": sum(
            isinstance(item, dict) and item.get("status") == "active"
            for item in records
        ),
        "smoke_tested": smoke,
        "errors": errors,
    }
