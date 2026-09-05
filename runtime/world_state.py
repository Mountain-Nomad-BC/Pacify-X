"""Bounded metadata-only projection of current Pacify-X operating state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4


MAX_WORLD_STATE_BYTES = 64 * 1024
SHA = re.compile(r"^[a-f0-9]{64}$")


def _read(root: Path, relative: str) -> Mapping[str, object]:
    try:
        value = json.loads((root / relative).read_text(encoding="utf-8"))
        return value if isinstance(value, Mapping) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_world_state(root: Path, *, source_revision: str) -> dict[str, object]:
    root = root.resolve(strict=True)
    if not SHA.fullmatch(source_revision):
        raise ValueError("world state requires exact source revision")
    project = _read(root, ".engineering-bootstrap/project-map/map-receipt.json")
    ledger = _read(root, "registry/operational_gap_ledger.head.json")
    semantic = _read(root, "registry/semantic_capability_index.json")
    agents = _read(root, "registry/agency_agent_registry.json")
    models = _read(root, "registry/models.json")
    staleness = _read(root, "registry/projection_staleness.json")
    authority = _read(root, "registry/authority_topology.json")
    hardware = _read(root, "registry/hardware_profile.json")
    release = _read(root, ".engineering-bootstrap/processing-order/release-identity.json")
    stale = sorted(
        str(item.get("projection_id"))
        for item in staleness.get("projections", ())
        if isinstance(item, Mapping) and item.get("stale") is True
    )
    dashboard = ledger.get("dashboard") if isinstance(ledger.get("dashboard"), Mapping) else {}
    blocker_count = int(dashboard.get("critical_high_blocker_count", 0) or 0)
    health = "BLOCKED" if blocker_count else ("STALE" if stale else "GREEN")
    components = {
        "authority": {
            "state": "GREEN" if authority.get("effect_count") else "UNVERIFIED",
            "reason_codes": [] if authority.get("effect_count") else ["authority_topology_missing"],
            "source_revision": source_revision,
            "evidence_reference": "registry/authority_topology.json",
        },
        "projections": {
            "state": "STALE" if stale else "GREEN",
            "reason_codes": ["stale_projection"] if stale else [],
            "source_revision": source_revision,
            "evidence_reference": "registry/projection_staleness.json",
        },
        "operations": {
            "state": "BLOCKED" if blocker_count else "GREEN",
            "reason_codes": ["critical_high_blocker"] if blocker_count else [],
            "source_revision": source_revision,
            "evidence_reference": "registry/operational_gap_ledger.head.json",
        },
    }
    body = {
        "schema_version": "px.world-state/1.0",
        "source_revision": source_revision,
        "health_state": health,
        "components": components,
        "project_map_revision": project.get("map_revision"),
        "project_source_inventory_sha256": project.get("source_inventory_sha256"),
        "ledger_checkpoint_sha256": ledger.get("checkpoint_sha256"),
        "ledger_event_count": ledger.get("event_count", 0),
        "open_blocker_ids": list(dashboard.get("critical_high_blocker_ids", ()))[:100],
        "open_blocker_count": blocker_count,
        "stale_projection_ids": stale[:100],
        "stale_projection_count": len(stale),
        "capability_count": len(semantic.get("records", ())),
        "agent_count": len(agents.get("agents", ())),
        "model_count": len(models.get("models", ())),
        "hardware_profile_revision": hardware.get("profile_sha256"),
        "authority_effect_count": authority.get("effect_count", 0),
        "release_campaign_id": release.get("campaign_id"),
        "release_state": release.get("state"),
        "recommended_next_actions": (
            ["resolve_current_blockers"] if blocker_count else (
                ["rebuild_stale_projections"] if stale else []
            )
        ),
        "details": {
            "project": ".engineering-bootstrap/project-map/map-receipt.json",
            "ledger": "registry/operational_gap_ledger.head.json",
            "capabilities": "registry/semantic_capability_index.json",
            "agents": "registry/agency_agent_registry.json",
            "models": "registry/models.json",
            "staleness": "registry/projection_staleness.json",
            "authority": "registry/authority_topology.json",
            "hardware": "registry/hardware_profile.json",
            "release": ".engineering-bootstrap/processing-order/release-identity.json",
        },
        "detail_bodies_hydrated": False,
    }
    result = {**body, "world_state_sha256": _digest(body)}
    validate_world_state(result, current_source_revision=source_revision)
    return result


def write_world_state(root: Path, *, source_revision: str) -> dict[str, object]:
    """Atomically publish the generated projection after validation."""
    root = root.resolve(strict=True)
    state = build_world_state(root, source_revision=source_revision)
    path = root / "registry/px_world_state.json"
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(prepared, path)
    return state


def load_world_state_for_startup(
    root: Path, *, current_source_revision: str | None
) -> dict[str, object]:
    """Read only the bounded projection and return a deterministic hydration plan."""
    root = root.resolve(strict=True)
    path = root / "registry/px_world_state.json"
    if not path.is_file():
        return {
            "state": "UNVERIFIED",
            "reason_codes": ["world_state_missing"],
            "hydrate": ["startup_core_metadata"],
            "world_state": None,
        }
    raw = path.read_bytes()
    if len(raw) > MAX_WORLD_STATE_BYTES:
        raise ValueError("invalid world state: size_budget")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("invalid world state: json") from error
    if not isinstance(value, Mapping):
        raise ValueError("invalid world state: schema")
    expected = current_source_revision or str(value.get("source_revision", ""))
    validate_world_state(value, current_source_revision=expected)
    stale = list(value.get("stale_projection_ids", ()))
    hydrate = ["startup_core_metadata"]
    hydrate.extend(f"projection:{item}" for item in stale)
    return {
        "state": value.get("health_state", "UNVERIFIED") if current_source_revision else "UNVERIFIED",
        "reason_codes": [] if current_source_revision else ["source_authority_not_supplied"],
        "hydrate": hydrate,
        "world_state": dict(value),
    }


def validate_world_state(
    state: Mapping[str, object], *, current_source_revision: str
) -> dict[str, object]:
    errors = []
    if state.get("schema_version") != "px.world-state/1.0":
        errors.append("schema")
    if state.get("source_revision") != current_source_revision:
        errors.append("stale_source")
    unsigned = {key: value for key, value in state.items() if key != "world_state_sha256"}
    if state.get("world_state_sha256") != _digest(unsigned):
        errors.append("hash")
    if state.get("detail_bodies_hydrated") is not False:
        errors.append("detail_hydration")
    encoded = json.dumps(state, sort_keys=True).encode()
    if len(encoded) > MAX_WORLD_STATE_BYTES:
        errors.append("size_budget")
    forbidden = {"prompt", "content", "memory_items", "logs", "credentials"}
    if forbidden & set(state):
        errors.append("private_payload")
    report = {"valid": not errors, "errors": errors, "bytes": len(encoded)}
    if errors:
        raise ValueError("invalid world state: " + ",".join(errors))
    return report
