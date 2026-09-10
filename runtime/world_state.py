"""Bounded metadata-only projection of current Pacify-X operating state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
from uuid import uuid4

from .archive_io import reject_path_links
from .json_io import bounded_json_text, load_json_object


MAX_WORLD_STATE_BYTES = 64 * 1024
SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_WORLD_SOURCE_BYTES = 2 * 1024 * 1024
MAX_WORLD_RECORDS = 20000
DETAIL_PATHS = {
    "project": ".engineering-bootstrap/project-map/map-receipt.json",
    "ledger": "registry/operational_gap_ledger.head.json",
    "capabilities": "registry/semantic_capability_index.json",
    "agents": "registry/agency_agent_registry.json",
    "models": "registry/models.json",
    "staleness": "registry/projection_staleness.json",
    "authority": "registry/authority_topology.json",
    "hardware": "registry/hardware_profile.json",
    "release": ".engineering-bootstrap/processing-order/release-identity.json",
}


def _read(root: Path, relative: str) -> dict[str, object] | None:
    path = root / relative
    reject_path_links(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("world-state source must be a regular file")
    if info.st_size > MAX_WORLD_SOURCE_BYTES:
        raise ValueError("world-state source byte budget exceeded")
    return load_json_object(
        path, max_bytes=MAX_WORLD_SOURCE_BYTES, max_depth=16, max_nodes=100000
    )


def _text(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 256
        or len(value.encode("utf-8")) > 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"invalid world state: {name} must be bounded metadata text")
    return value


def _sha(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or SHA.fullmatch(value) is None:
        raise ValueError(f"invalid world state: {name} must be an exact sha256")
    return value


def _count(value: object, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= 2**31 - 1:
        raise ValueError(
            f"invalid world state: {name} must be a bounded nonnegative integer"
        )
    return value


def _ids(value: object, name: str, *, limit: int) -> list[str]:
    if type(value) is not list or len(value) > limit:
        raise ValueError(f"invalid world state: {name} requires a bounded list")
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"invalid world state: duplicate {name}")
    return value


def _record_count(value: dict | None, key: str) -> int | None:
    if value is None:
        return None
    rows = value.get(key)
    if (
        type(rows) is not list
        or len(rows) > MAX_WORLD_RECORDS
        or any(type(row) is not dict for row in rows)
    ):
        raise ValueError(f"world-state source {key} requires bounded metadata records")
    return len(rows)


def _health(blockers: int | None, stale: int | None) -> str:
    if blockers:
        return "BLOCKED"
    if stale:
        return "STALE"
    if blockers is None or stale is None:
        return "UNVERIFIED"
    return "GREEN"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_world_state(root: Path, *, source_revision: str) -> dict[str, object]:
    reject_path_links(root)
    root = root.resolve(strict=True)
    _sha(source_revision, "source_revision")
    sources = {key: _read(root, path) for key, path in DETAIL_PATHS.items()}
    (
        project,
        ledger,
        semantic,
        agents,
        models,
        staleness,
        authority,
        hardware,
        release,
    ) = (sources[key] for key in DETAIL_PATHS)
    stale = []
    if staleness is not None:
        _record_count(staleness, "projections")
        seen = set()
        for row in staleness["projections"]:
            identifier = _text(row.get("projection_id"), "projection_id")
            if identifier in seen or type(row.get("stale")) is not bool:
                raise ValueError(
                    "world-state projection metadata is duplicate or mistyped"
                )
            seen.add(identifier)
            if row["stale"]:
                stale.append(identifier)
        stale.sort()
    stale_count = len(stale) if staleness is not None else None
    blocker_count = None
    blocker_ids = []
    if ledger is not None:
        dashboard = ledger.get("dashboard")
        if type(dashboard) is not dict:
            raise ValueError("world-state ledger dashboard is missing or malformed")
        blocker_count = _count(
            dashboard.get("critical_high_blocker_count"), "open_blocker_count"
        )
        blocker_ids = _ids(
            dashboard.get("critical_high_blocker_ids"),
            "open_blocker_ids",
            limit=MAX_WORLD_RECORDS,
        )
        if len(blocker_ids) != blocker_count:
            raise ValueError(
                "world-state ledger blocker count differs from its declared IDs"
            )
    authority_count = (
        _count(authority.get("effect_count"), "authority_effect_count")
        if authority is not None
        else None
    )
    if authority is not None and authority_count != _record_count(authority, "effects"):
        raise ValueError(
            "world-state authority count differs from its declared effects"
        )
    health = _health(blocker_count, stale_count)
    components = {
        "authority": {
            "state": "GREEN" if authority_count else "UNVERIFIED",
            "reason_codes": [] if authority_count else ["authority_topology_missing"],
            "source_revision": source_revision,
            "evidence_reference": "registry/authority_topology.json",
        },
        "projections": {
            "state": _health(0, stale_count),
            "reason_codes": ["projection_metadata_missing"]
            if stale_count is None
            else (["stale_projection"] if stale else []),
            "source_revision": source_revision,
            "evidence_reference": "registry/projection_staleness.json",
        },
        "operations": {
            "state": _health(blocker_count, 0),
            "reason_codes": ["ledger_metadata_missing"]
            if blocker_count is None
            else (["critical_high_blocker"] if blocker_count else []),
            "source_revision": source_revision,
            "evidence_reference": "registry/operational_gap_ledger.head.json",
        },
    }
    body = {
        "schema_version": "px.world-state/1.0",
        "source_revision": source_revision,
        "health_state": health,
        "components": components,
        "project_map_revision": (project or {}).get("map_revision"),
        "project_source_inventory_sha256": (project or {}).get(
            "source_inventory_sha256"
        ),
        "ledger_checkpoint_sha256": (ledger or {}).get("checkpoint_sha256"),
        "ledger_event_count": ledger.get("event_count") if ledger is not None else None,
        "open_blocker_ids": sorted(blocker_ids)[:100],
        "open_blocker_count": blocker_count,
        "stale_projection_ids": stale[:100],
        "stale_projection_count": stale_count,
        "capability_count": _record_count(semantic, "records"),
        "agent_count": _record_count(agents, "agents"),
        "model_count": _record_count(models, "models"),
        "hardware_profile_revision": (hardware or {}).get("profile_sha256"),
        "authority_effect_count": authority_count,
        "release_campaign_id": (release or {}).get("campaign_id"),
        "release_state": (release or {}).get("state"),
        "recommended_next_actions": (
            ["resolve_current_blockers"]
            if blocker_count
            else (["rebuild_stale_projections"] if stale else [])
        ),
        "details": dict(DETAIL_PATHS),
        "detail_bodies_hydrated": False,
    }
    if health == "GREEN" and (
        any(item["state"] == "UNVERIFIED" for item in components.values())
        or any(
            body[key] is None
            for key in ("capability_count", "agent_count", "model_count")
        )
    ):
        body["health_state"] = "UNVERIFIED"
    bounded_json_text(body, max_bytes=MAX_WORLD_STATE_BYTES)
    result = {**body, "world_state_sha256": _digest(body)}
    validate_world_state(result, current_source_revision=source_revision)
    return result


def write_world_state(root: Path, *, source_revision: str) -> dict[str, object]:
    """Atomically publish the generated projection after validation."""
    reject_path_links(root)
    root = root.resolve(strict=True)
    state = build_world_state(root, source_revision=source_revision)
    path = root / "registry/px_world_state.json"
    reject_path_links(path)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(prepared, path)
    return state


def load_world_state_for_startup(
    root: Path, *, current_source_revision: str | None
) -> dict[str, object]:
    """Read only the bounded projection and return a deterministic hydration plan."""
    reject_path_links(root)
    root = root.resolve(strict=True)
    path = root / "registry/px_world_state.json"
    reject_path_links(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return {
            "state": "UNVERIFIED",
            "reason_codes": ["world_state_missing"],
            "hydrate": ["startup_core_metadata"],
            "world_state": None,
        }
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_WORLD_STATE_BYTES:
        raise ValueError("invalid world state: file or size budget")
    value = load_json_object(
        path, max_bytes=MAX_WORLD_STATE_BYTES, max_depth=8, max_nodes=2048
    )
    expected = (
        value.get("source_revision")
        if current_source_revision is None
        else current_source_revision
    )
    validate_world_state(value, current_source_revision=expected)
    stale = list(value.get("stale_projection_ids", ()))
    hydrate = ["startup_core_metadata"]
    hydrate.extend(f"projection:{item}" for item in stale)
    return {
        "state": value.get("health_state", "UNVERIFIED")
        if current_source_revision
        else "UNVERIFIED",
        "reason_codes": []
        if current_source_revision
        else ["source_authority_not_supplied"],
        "hydrate": hydrate,
        "world_state": dict(value),
    }


def validate_world_state(
    state: Mapping[str, object], *, current_source_revision: str
) -> dict[str, object]:
    fields = {
        "schema_version",
        "source_revision",
        "world_state_sha256",
        "health_state",
        "components",
        "project_map_revision",
        "project_source_inventory_sha256",
        "ledger_checkpoint_sha256",
        "ledger_event_count",
        "open_blocker_ids",
        "open_blocker_count",
        "stale_projection_ids",
        "stale_projection_count",
        "capability_count",
        "agent_count",
        "model_count",
        "hardware_profile_revision",
        "authority_effect_count",
        "release_campaign_id",
        "release_state",
        "recommended_next_actions",
        "details",
        "detail_bodies_hydrated",
    }
    if type(state) is not dict or len(state) != len(fields) or set(state) != fields:
        raise ValueError("invalid world state: exact metadata fields required")
    _sha(current_source_revision, "current_source_revision")
    _sha(state["source_revision"], "source_revision")
    _sha(state["world_state_sha256"], "world_state_sha256")
    for key in (
        "project_source_inventory_sha256",
        "ledger_checkpoint_sha256",
        "hardware_profile_revision",
    ):
        _sha(state[key], key, optional=True)
    for key in ("project_map_revision", "release_campaign_id", "release_state"):
        _text(state[key], key, optional=True)
    for key in (
        "ledger_event_count",
        "open_blocker_count",
        "stale_projection_count",
        "capability_count",
        "agent_count",
        "model_count",
        "authority_effect_count",
    ):
        _count(state[key], key, optional=True)
    for key, count_key in (
        ("open_blocker_ids", "open_blocker_count"),
        ("stale_projection_ids", "stale_projection_count"),
    ):
        values = _ids(state[key], key, limit=100)
        count = state[count_key]
        if values != sorted(values) or len(values) != (
            min(count, 100) if count is not None else 0
        ):
            raise ValueError("invalid world state: count/list metadata mismatch")
    details = state["details"]
    if (
        type(details) is not dict
        or len(details) != len(DETAIL_PATHS)
        or set(details) != set(DETAIL_PATHS)
        or any(
            type(details[key]) is not str or details[key] != value
            for key, value in DETAIL_PATHS.items()
        )
    ):
        raise ValueError(
            "invalid world state: detail locators must be canonical metadata paths"
        )
    components = state["components"]
    expected_states = {
        "authority": "GREEN" if state["authority_effect_count"] else "UNVERIFIED",
        "operations": _health(state["open_blocker_count"], 0),
        "projections": _health(0, state["stale_projection_count"]),
    }
    expected_reasons = {
        "authority": []
        if state["authority_effect_count"]
        else ["authority_topology_missing"],
        "operations": ["ledger_metadata_missing"]
        if state["open_blocker_count"] is None
        else (["critical_high_blocker"] if state["open_blocker_count"] else []),
        "projections": ["projection_metadata_missing"]
        if state["stale_projection_count"] is None
        else (["stale_projection"] if state["stale_projection_count"] else []),
    }
    if (
        type(components) is not dict
        or len(components) != 3
        or set(components) != set(expected_states)
    ):
        raise ValueError("invalid world state: exact component metadata required")
    for key, expected_state in expected_states.items():
        component = components[key]
        if (
            type(component) is not dict
            or len(component) != 4
            or set(component)
            != {"state", "reason_codes", "source_revision", "evidence_reference"}
        ):
            raise ValueError("invalid world state: exact component fields required")
        reasons = _ids(component["reason_codes"], "reason_codes", limit=8)
        reference = DETAIL_PATHS[
            {
                "authority": "authority",
                "operations": "ledger",
                "projections": "staleness",
            }[key]
        ]
        if (
            type(component["state"]) is not str
            or component["state"] != expected_state
            or reasons != expected_reasons[key]
            or component["source_revision"] != state["source_revision"]
            or type(component["evidence_reference"]) is not str
            or component["evidence_reference"] != reference
        ):
            raise ValueError(
                "invalid world state: component metadata disagrees with its counts or revision"
            )
    health = _health(state["open_blocker_count"], state["stale_projection_count"])
    if health == "GREEN" and (
        "UNVERIFIED" in expected_states.values()
        or any(
            state[key] is None
            for key in ("capability_count", "agent_count", "model_count")
        )
    ):
        health = "UNVERIFIED"
    if type(state["health_state"]) is not str or state["health_state"] != health:
        raise ValueError("invalid world state: health metadata is inconsistent")
    actions = _ids(
        state["recommended_next_actions"], "recommended_next_actions", limit=8
    )
    expected_actions = (
        ["resolve_current_blockers"]
        if state["open_blocker_count"]
        else (["rebuild_stale_projections"] if state["stale_projection_count"] else [])
    )
    if actions != expected_actions:
        raise ValueError("invalid world state: next actions disagree with metadata")
    encoded = bounded_json_text(state, max_bytes=MAX_WORLD_STATE_BYTES).encode("utf-8")
    errors = []
    if state.get("schema_version") != "px.world-state/1.0":
        errors.append("schema")
    if state.get("source_revision") != current_source_revision:
        errors.append("stale_source")
    unsigned = {
        key: value for key, value in state.items() if key != "world_state_sha256"
    }
    if state.get("world_state_sha256") != _digest(unsigned):
        errors.append("hash")
    if state.get("detail_bodies_hydrated") is not False:
        errors.append("detail_hydration")
    report = {"valid": not errors, "errors": errors, "bytes": len(encoded)}
    if errors:
        raise ValueError("invalid world state: " + ",".join(errors))
    return report
