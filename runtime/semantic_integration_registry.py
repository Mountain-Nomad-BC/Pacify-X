"""Non-authoritative semantic integration inventory for normal PX admission."""
from __future__ import annotations

from .semantic_capability_projection import OPERATIONS, operation_catalog
from .semantic_context_profiles import context_names
from .semantic_mode_profiles import mode_names


def integration_inventory() -> dict[str, object]:
    available = operation_catalog(available_only=True)
    wave_names = {operation.source for operation in available.values()}
    available_waves = sorted(
        wave_names,
        key=lambda value: (
            0, int(value[4:])
        ) if value.startswith("wave") and value[4:].isdigit() else (1, value),
    )
    return {
        "schema_version": "px.semantic-integration-candidate/1.2",
        "authoritative": False,
        "admission_required": True,
        "operations": sorted(available),
        "declared_operations": [item.name for item in OPERATIONS],
        "contexts": list(context_names()),
        "modes": list(mode_names()),
        "installed_waves": available_waves,
        # Required waves reflect the actually installed candidate surface rather than a
        # stale package-era constant.  Admission still happens elsewhere.
        "waves_required": available_waves,
    }
