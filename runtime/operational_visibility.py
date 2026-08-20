"""Canonical operational-event and route-observer truth boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractValidationError, validate_instance


OPERATION_EVENT_SCHEMA = Path("contracts/operations/operation-event.schema.json")
ROUTE_REGISTRY_SCHEMA = Path(
    "contracts/operations/route-observer-registry.schema.json"
)
TIER_MECHANISMS = {"A": "mediator", "B": "observer", "C": "attestation"}


def validate_operation_event(root: Path, event: Mapping[str, object]) -> dict[str, Any]:
    """Validate one event and reject content capture without explicit classification."""
    errors: list[str] = []
    try:
        validate_instance(dict(event), root / OPERATION_EVENT_SCHEMA)
    except (ContractValidationError, OSError, ValueError) as error:
        errors.append(str(error))
    capture = event.get("capture")
    if isinstance(capture, Mapping):
        classification = capture.get("classification")
        if capture.get("payload_included") is True and classification != "content_authorized":
            errors.append("payload inclusion requires content_authorized classification")
    return {"schema_version": "1.0", "valid": not errors, "errors": errors}


def validate_route_registry(root: Path) -> dict[str, Any]:
    """Validate route declarations and enforce honest tier/mechanism pairings."""
    path = root / "registry" / "operation_route_registry.json"
    errors: list[str] = []
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
        validate_instance(registry, root / ROUTE_REGISTRY_SCHEMA)
    except (ContractValidationError, OSError, UnicodeError, ValueError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "route_count": 0,
            "advertised_count": 0,
            "certifiable": False,
            "tiers": {tier: 0 for tier in "ABCD"},
            "errors": [str(error)],
        }
    routes = registry.get("routes", ())
    seen: set[str] = set()
    tiers = {tier: 0 for tier in "ABCD"}
    for route in routes:
        route_id = str(route["route_id"])
        if route_id in seen:
            errors.append(f"{route_id}: duplicate route")
        seen.add(route_id)
        tier = str(route["coverage_tier"])
        tiers[tier] += 1
        mechanism = str(route["instrumentation"]["kind"])
        expected = TIER_MECHANISMS.get(tier)
        if expected is not None and mechanism != expected:
            errors.append(
                f"{route_id}: Tier {tier} requires {expected}, found {mechanism}"
            )
        if tier == "D" and route["blind_spot_state"] == "none":
            errors.append(f"{route_id}: Tier D must declare a blind spot")
        if tier != "D" and route["blind_spot_state"] == "unobserved":
            errors.append(f"{route_id}: observed tier cannot be unobserved")
    advertised = [route for route in routes if route["advertised"]]
    tier_d_advertised = [
        route["route_id"]
        for route in advertised
        if route["coverage_tier"] == "D"
    ]
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "route_count": len(routes),
        "advertised_count": len(advertised),
        "certifiable": not errors and not tier_d_advertised,
        "tiers": tiers,
        "tier_d_advertised": tier_d_advertised,
        "errors": errors,
    }

