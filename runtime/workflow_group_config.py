"""Closed prepared-group task configuration; declaration grants no execution."""
from __future__ import annotations

from dataclasses import asdict
from collections.abc import Mapping
import json
import re

from .json_io import bounded_canonical_json_bytes

EXECUTION_MODE = "prepared-model-group"
MAX_CONFIG_BYTES = 256 * 1024
AGENT_SPEC_FIELDS = frozenset({
    "agent_id", "version", "project_id", "owner", "harness_id",
    "instruction_sha256", "capability_binding_ids", "effect_grant_ids",
    "required_tests", "lifecycle", "model", "tool_binding_ids",
    "memory_binding_ids", "handoff_agent_ids", "input_schema", "output_schema",
})
ARRAY_FIELDS = frozenset({"capability_binding_ids", "effect_grant_ids", "required_tests",
                         "tool_binding_ids", "memory_binding_ids", "handoff_agent_ids"})
TEXT_FIELDS = frozenset({"agent_id", "version", "project_id", "owner", "harness_id",
                        "instruction_sha256", "lifecycle"})


def agent_spec_from_group_config(value: Mapping):
    """Decode the same exact native AgentSpec fields consumed by the worker."""
    from .studio_models import AgentSpec, canonical_bytes
    if type(value) is not dict or set(value) != AGENT_SPEC_FIELDS:
        raise ValueError("prepared-group task requires the exact canonical agent spec")
    for name in TEXT_FIELDS:
        if type(value[name]) is not str or not value[name] or len(value[name]) > 256:
            raise ValueError("prepared-group agent identities must be bounded strings")
    for name in ARRAY_FIELDS:
        items = value[name]
        if (type(items) is not list or len(items) > 512
                or any(type(item) is not str or not item or len(item) > 256 for item in items)
                or len(items) != len(set(items))):
            raise ValueError("prepared-group bindings must be bounded unique string arrays")
    for name in ("model", "input_schema", "output_schema"):
        if type(value[name]) is not dict:
            raise ValueError("prepared-group agent contracts must be objects")
    decoded = dict(value)
    for name in ARRAY_FIELDS:
        decoded[name] = tuple(value[name])
    spec = AgentSpec(**decoded)
    if canonical_bytes(asdict(spec)) != canonical_bytes(value):
        raise ValueError("prepared-group agent spec must already be canonical")
    return spec


def validate_prepared_group_node_config(value: Mapping) -> dict:
    """Validate a closed declaration without reading or executing any plan.

    Canonical plan resolution, exact group-member denominator, placement/profile
    integrity, approval and provider/containment admission remain native runtime
    responsibilities. This parser accepts no filesystem path or raw branch array.
    """
    if not isinstance(value, Mapping) or set(value) != {
            "execution_mode", "prepared_group_reference", "agent_spec", "placements"}:
        raise ValueError("prepared-group node config requires its exact four fields")
    image = bounded_canonical_json_bytes(dict(value), max_bytes=MAX_CONFIG_BYTES)
    normalized = json.loads(image)
    if normalized["execution_mode"] != EXECUTION_MODE:
        raise ValueError("unsupported task execution mode")
    reference = normalized["prepared_group_reference"]
    if type(reference) is not dict or set(reference) != {"schema_version", "plan_id", "plan_sha256"}:
        raise ValueError("exact versioned prepared-group reference required")
    if (reference["schema_version"] != "px.prepared-group-reference/1.0"
            or type(reference["plan_id"]) is not str
            or re.fullmatch(r"task-plan-[0-9a-f]{24}", reference["plan_id"]) is None
            or type(reference["plan_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", reference["plan_sha256"]) is None):
        raise ValueError("prepared-group reference identity/digest is invalid")
    agent_spec_from_group_config(normalized["agent_spec"])
    placements = normalized["placements"]
    if type(placements) is not dict or not 1 <= len(placements) <= 12:
        raise ValueError("prepared-group placements require between one and twelve members")
    for model_id, placement in placements.items():
        if (type(model_id) is not str or not model_id or len(model_id.encode("utf-8")) > 240
                or any(ord(char) < 32 for char in model_id)
                or type(placement) is not dict or not placement or len(placement) > 128):
            raise ValueError("prepared-group placements require bounded model identities and objects")
        if placement.get("model_id") != model_id:
            raise ValueError("placement identity differs from its exact model key")
    return normalized
