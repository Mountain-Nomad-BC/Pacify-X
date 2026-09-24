"""Render capability projections as client-neutral tool descriptors."""
from __future__ import annotations
from .semantic_capability_projection import operation_catalog
from .semantic_integration_types import CapabilityProjection


def projected_tools(projection: CapabilityProjection) -> tuple[dict[str, object], ...]:
    catalog = operation_catalog()
    return tuple({
        "name": name, "effects": [effect.value for effect in catalog[name].effects], "risk": catalog[name].risk,
        "source": catalog[name].source, "mutation": catalog[name].mutation,
        "authority_note": "Exposure is not execution authority; PX policy/claim/user-approval gates remain independent.",
    } for name in projection.operations)
