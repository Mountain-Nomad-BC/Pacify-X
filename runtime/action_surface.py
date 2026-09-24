"""Deterministic action discovery metadata derived from admitted PX authorities.

This module is deliberately non-authoritative.  It resolves user-facing names to
admitted action/capability identifiers and emits preflight metadata.  Execution,
policy, effect grants, approvals, repository claims, and step-up verification are
owned by their existing PX authorities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9_.:-]+")
_MAX_DESCRIPTORS = 10000
_MAX_ALIASES_PER_DESCRIPTOR = 128
_MAX_TEXT_BYTES = 16384


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def normalize_action_text(value: str) -> str:
    if type(value) is not str or len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError("action text must be bounded text")
    lowered = value.casefold()
    for pattern, replacement in (
        (r"\bcan you\b", ""),
        (r"\bcould you\b", ""),
        (r"\bplease\b", ""),
        (r"\bbring up\b", "open"),
        (r"\bpull up\b", "open"),
        (r"\btake me to\b", "open"),
        (r"\blet me see\b", "show"),
    ):
        lowered = re.sub(pattern, replacement, lowered)
    return _WS.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def _bounded_text(value: object, label: str, *, maximum: int = 4096, required: bool = False) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{label} must not be empty")
    if len(result.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds byte budget")
    return result


@dataclass(frozen=True, slots=True)
class ActionDescriptor:
    """Read-only discovery projection of an already-admitted PX action/capability."""

    action_id: str
    capability_id: str
    description: str
    aliases: tuple[str, ...] = ()
    parameter_schema: Mapping[str, Any] = field(default_factory=dict)
    allowed_roles: tuple[str, ...] = ()
    requires_step_up: bool = False
    mutating: bool = False
    risk_level: str = "R1"
    idempotency: str = "idempotent"
    required_context_fields: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    queue_eligible: bool = False
    enabled: bool = True
    authority_revision: str = ""

    def __post_init__(self) -> None:
        for label, value in (("action_id", self.action_id), ("capability_id", self.capability_id)):
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"{label} must be a bounded identifier")
        _bounded_text(self.description, "description", maximum=8192)
        if type(self.requires_step_up) is not bool or type(self.mutating) is not bool or type(self.queue_eligible) is not bool or type(self.enabled) is not bool:
            raise ValueError("action descriptor flags must be literal booleans")
        if len(self.aliases) > _MAX_ALIASES_PER_DESCRIPTOR:
            raise ValueError("too many action aliases")
        for collection_name, values in (
            ("aliases", self.aliases),
            ("allowed_roles", self.allowed_roles),
            ("required_context_fields", self.required_context_fields),
            ("tags", self.tags),
        ):
            if type(values) is not tuple or any(type(item) is not str or not item.strip() or len(item.encode("utf-8")) > 512 for item in values):
                raise ValueError(f"{collection_name} must be bounded nonempty text tuples")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("action aliases must be unique")
        if type(self.parameter_schema) not in (dict,) and not isinstance(self.parameter_schema, Mapping):
            raise ValueError("parameter_schema must be a mapping")
        # Prove serializability now instead of failing while generating a receipt.
        _canonical(dict(self.parameter_schema))
        _bounded_text(self.risk_level, "risk_level", maximum=64, required=True)
        _bounded_text(self.idempotency, "idempotency", maximum=128, required=True)
        _bounded_text(self.authority_revision, "authority_revision", maximum=256)

    @property
    def descriptor_sha256(self) -> str:
        return _sha({
            "action_id": self.action_id,
            "capability_id": self.capability_id,
            "description": self.description,
            "aliases": list(self.aliases),
            "parameter_schema": dict(self.parameter_schema),
            "allowed_roles": list(self.allowed_roles),
            "requires_step_up": self.requires_step_up,
            "mutating": self.mutating,
            "risk_level": self.risk_level,
            "idempotency": self.idempotency,
            "required_context_fields": list(self.required_context_fields),
            "tags": list(self.tags),
            "queue_eligible": self.queue_eligible,
            "enabled": self.enabled,
            "authority_revision": self.authority_revision,
        })

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ActionDescriptor":
        if not isinstance(payload, Mapping):
            raise ValueError("action descriptor payload must be a mapping")
        def text_tuple(name: str) -> tuple[str, ...]:
            raw = payload.get(name, ())
            if not isinstance(raw, (list, tuple)):
                raise ValueError(f"{name} must be a list or tuple")
            return tuple(str(item) for item in raw)
        for flag in ("requires_step_up", "mutating", "queue_eligible", "enabled"):
            if flag in payload and type(payload[flag]) is not bool:
                raise ValueError(f"{flag} must be a literal boolean")
        action_id = str(payload["action_id"])
        return cls(
            action_id=action_id,
            capability_id=str(payload.get("capability_id") or action_id),
            description=str(payload.get("description") or ""),
            aliases=text_tuple("aliases"),
            parameter_schema=dict(payload.get("parameter_schema") or {}),
            allowed_roles=text_tuple("allowed_roles"),
            requires_step_up=payload.get("requires_step_up", False),
            mutating=payload.get("mutating", False),
            risk_level=str(payload.get("risk_level") or "R1"),
            idempotency=str(payload.get("idempotency") or "idempotent"),
            required_context_fields=text_tuple("required_context_fields"),
            tags=text_tuple("tags"),
            queue_eligible=payload.get("queue_eligible", False),
            enabled=payload.get("enabled", True),
            authority_revision=str(payload.get("authority_revision") or ""),
        )


@dataclass(frozen=True, slots=True)
class ActionResolution:
    status: str
    action_id: str | None
    capability_id: str | None
    confidence: float
    reason: str
    matched_alias: str | None = None
    descriptor_sha256: str | None = None
    surface_sha256: str = ""
    authority_granted: bool = False
    preflight: Mapping[str, Any] = field(default_factory=dict)


class ActionSurface:
    """Deterministic discovery seam.  It never authorizes or executes an action."""

    def __init__(self, descriptors: Iterable[ActionDescriptor]) -> None:
        rows = tuple(descriptors)
        if len(rows) > _MAX_DESCRIPTORS:
            raise ValueError("action surface exceeds descriptor budget")
        if any(type(row) is not ActionDescriptor for row in rows):
            raise ValueError("action surface requires ActionDescriptor records")
        by_id: dict[str, ActionDescriptor] = {}
        aliases: dict[str, tuple[str, str]] = {}
        for descriptor in rows:
            if descriptor.action_id in by_id:
                raise ValueError(f"duplicate action id: {descriptor.action_id}")
            by_id[descriptor.action_id] = descriptor
            for alias in (descriptor.action_id, descriptor.capability_id, *descriptor.aliases):
                normalized = normalize_action_text(alias)
                if not normalized:
                    continue
                owner = aliases.get(normalized)
                if owner is not None and owner[0] != descriptor.action_id:
                    raise ValueError(f"ambiguous action alias {alias!r}: {owner[0]} vs {descriptor.action_id}")
                aliases[normalized] = (descriptor.action_id, alias)
        self._descriptors = by_id
        self._aliases = aliases
        self._surface_sha256 = _sha([
            [row.action_id, row.descriptor_sha256]
            for row in sorted(rows, key=lambda item: item.action_id)
        ])

    @property
    def surface_sha256(self) -> str:
        return self._surface_sha256

    def list(self) -> tuple[ActionDescriptor, ...]:
        return tuple(sorted(self._descriptors.values(), key=lambda item: item.action_id))

    def resolve(
        self,
        text: str,
        *,
        roles: Iterable[str] = (),
        step_up_verified: bool = False,
        available_context_fields: Iterable[str] = (),
    ) -> ActionResolution:
        if type(step_up_verified) is not bool:
            raise ValueError("step_up_verified must be a literal boolean")
        normalized = normalize_action_text(text)
        if not normalized:
            return ActionResolution("unsupported", None, None, 0.0, "empty_action_text", surface_sha256=self.surface_sha256)
        candidates: list[tuple[float, str, str]] = []
        text_tokens = set(normalized.split())
        for alias_norm, (action_id, original_alias) in self._aliases.items():
            descriptor = self._descriptors[action_id]
            if not descriptor.enabled:
                continue
            if alias_norm == normalized:
                score = 1.0
            elif re.search(rf"(?<![a-z0-9_.:-]){re.escape(alias_norm)}(?![a-z0-9_.:-])", normalized):
                score = 0.95
            else:
                alias_tokens = set(alias_norm.split())
                if not alias_tokens:
                    continue
                overlap = len(text_tokens & alias_tokens) / len(alias_tokens)
                if overlap < 0.80:
                    continue
                score = 0.80 + min(0.14, overlap * 0.14)
            candidates.append((score, action_id, original_alias))
        if not candidates:
            return ActionResolution("unsupported", None, None, 0.0, "no_deterministic_action_match", surface_sha256=self.surface_sha256)
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        best_score = candidates[0][0]
        best_ids = {item[1] for item in candidates if math.isclose(item[0], best_score, rel_tol=0.0, abs_tol=1e-12)}
        if len(best_ids) != 1:
            return ActionResolution("ambiguous", None, None, best_score, "multiple_equal_action_matches", surface_sha256=self.surface_sha256)
        _, action_id, matched_alias = candidates[0]
        descriptor = self._descriptors[action_id]
        supplied_roles = {str(item) for item in roles}
        present = {str(item) for item in available_context_fields}
        warnings: list[str] = []
        if descriptor.allowed_roles and not supplied_roles.intersection(descriptor.allowed_roles):
            warnings.append("role_prerequisite_unsatisfied")
        if descriptor.requires_step_up and not step_up_verified:
            warnings.append("step_up_prerequisite_unsatisfied")
        missing_context = sorted(set(descriptor.required_context_fields) - present)
        if missing_context:
            warnings.append("context_prerequisite_unsatisfied")
        return ActionResolution(
            status="candidate",
            action_id=descriptor.action_id,
            capability_id=descriptor.capability_id,
            confidence=best_score,
            reason="deterministic_action_projection_match",
            matched_alias=matched_alias,
            descriptor_sha256=descriptor.descriptor_sha256,
            surface_sha256=self.surface_sha256,
            authority_granted=False,
            preflight={
                "warnings": warnings,
                "missing_context_fields": missing_context,
                "mutating": descriptor.mutating,
                "risk_level": descriptor.risk_level,
                "idempotency": descriptor.idempotency,
                "queue_eligible": descriptor.queue_eligible,
                "parameter_schema": dict(descriptor.parameter_schema),
                "authority_revision": descriptor.authority_revision,
            },
        )


def project_capability_descriptor(
    capability: Mapping[str, Any],
    *,
    effects: Iterable[str] = (),
    allowed_roles: Iterable[str] = (),
    requires_step_up: bool = False,
    queue_eligible: bool = False,
    parameter_schema: Mapping[str, Any] | None = None,
    authority_revision: str = "",
) -> ActionDescriptor:
    """Build discovery metadata from a trusted PX capability projection.

    The returned descriptor remains non-authoritative even when it describes a
    mutating capability.
    """
    if not isinstance(capability, Mapping):
        raise ValueError("capability must be a mapping")
    for flag_name, flag in (("requires_step_up", requires_step_up), ("queue_eligible", queue_eligible)):
        if type(flag) is not bool:
            raise ValueError(f"{flag_name} must be a literal boolean")
    capability_id = _bounded_text(capability.get("capability_id"), "capability_id", maximum=256, required=True)
    effect_rows = tuple(effects)
    if any(type(item) is not str or not item.strip() for item in effect_rows):
        raise ValueError("effects must contain nonempty text")
    effect_set = set(effect_rows)
    read_only = {"read", "read_local", "workspace-read", "observe", "host-ui"}
    def declared_sequence(name: str) -> tuple[object, ...]:
        value = capability.get(name, ()) or ()
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"capability {name} must be a list or tuple")
        return tuple(value)
    aliases = tuple(dict.fromkeys(
        str(item) for item in (
            *declared_sequence("aliases"),
            *declared_sequence("triggers"),
            *declared_sequence("synonyms"),
        ) if str(item).strip()
    ))
    required = tuple(dict.fromkeys(
        str(item) for item in (
            *declared_sequence("required_inputs"),
            *declared_sequence("inputs"),
        ) if str(item).strip()
    ))
    return ActionDescriptor(
        action_id=capability_id,
        capability_id=capability_id,
        description=str(capability.get("purpose") or ""),
        aliases=aliases,
        parameter_schema=dict(parameter_schema or {}),
        allowed_roles=tuple(str(item) for item in allowed_roles),
        requires_step_up=requires_step_up,
        mutating=bool(effect_set - read_only),
        risk_level=str(capability.get("risk") or "R1"),
        idempotency="idempotency_key_required" if effect_set - read_only else "idempotent",
        required_context_fields=required,
        tags=tuple(str(item) for item in capability.get("capability_tags", ())),
        queue_eligible=queue_eligible,
        enabled=str(capability.get("status") or "") in {"admitted", "active"},
        authority_revision=authority_revision,
    )
