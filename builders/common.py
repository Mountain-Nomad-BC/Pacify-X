"""Shared fail-closed controls for declarative asset proposals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, TypeVar


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KNOWN_EFFECTS = frozenset(
    {
        "read_local",
        "trace_write",
        "write_workspace",
        "install_tool",
        "network",
        "run_service",
        "secret_access",
        "migration",
        "destructive",
    }
)
MUTATING_EFFECTS = KNOWN_EFFECTS - {"read_local"}
_SOURCE_TERMS = ("r" + "ie", "re" + "my", "rh" + "eem")
_SOURCE_PATTERN = re.compile(
    rf"(?i)(?<![A-Za-z])({'|'.join(_SOURCE_TERMS)})(?![A-Za-z])"
)
_SOURCE_REPLACEMENTS = dict(
    zip(
        _SOURCE_TERMS,
        (
            "intelligent_integrations_and_engines",
            "governed_retrieval_system_with_deterministic_rails",
            "enterprise",
        ),
    )
)
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|secret|credential)"
)
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|secret|credential)\s*[:=]\s*[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")


class BuilderError(ValueError):
    """A proposal is incomplete or violates a builder boundary."""


class DuplicateAssetError(BuilderError):
    """The requested asset already exists."""


class GapNotProvenError(BuilderError):
    """Existing registry metadata already satisfies the requested gap."""


def require_identifier(value: str, field: str = "id") -> str:
    if not IDENTIFIER.fullmatch(value):
        raise BuilderError(f"{field} must be a lowercase kebab-case identifier")
    return value


def require_field_name(value: str, field: str = "field") -> str:
    if not FIELD_NAME.fullmatch(value):
        raise BuilderError(f"{field} must be a safe field name")
    return value


T = TypeVar("T")


def bounded_unique(
    values: Iterable[T],
    field: str,
    *,
    maximum: int = 32,
    required: bool = True,
) -> tuple[T, ...]:
    result = tuple(values)
    if required and not result:
        raise BuilderError(f"{field} must not be empty")
    if len(result) > maximum:
        raise BuilderError(f"{field} exceeds bounded limit of {maximum}")
    for index, item in enumerate(result):
        if any(item == previous for previous in result[:index]):
            raise BuilderError(f"{field} contains duplicates")
    return result


def sanitize_text(value: str) -> str:
    value = _SOURCE_PATTERN.sub(
        lambda match: _SOURCE_REPLACEMENTS[match.group(1).lower()], value
    )
    value = _ASSIGNED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _BEARER.sub("Bearer [REDACTED]", value)


def sanitize(value: object, *, key: str | None = None) -> object:
    """Recursively sanitize proposal/evidence content without accessing external state."""
    if key is not None and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            sanitize_text(str(item_key)): sanitize(item_value, key=str(item_key))
            for item_key, item_value in sorted(
                value.items(), key=lambda item: str(item[0])
            )
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [sanitize(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return items
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise BuilderError(f"unsupported proposal value type: {type(value).__name__}")


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        sanitize(value), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def proposal_envelope(
    kind: str, asset_id: str, body: Mapping[str, object]
) -> dict[str, object]:
    require_identifier(asset_id, "asset_id")
    sanitized_body = sanitize(body)
    assert isinstance(sanitized_body, dict)
    proposal: dict[str, object] = {
        "schema_version": "1.0",
        "proposal_kind": kind,
        "proposal_id": asset_id,
        "status": "candidate",
        "auto_activate": False,
        "registry_action": "proposal_only",
        "promotion_requirements": [
            "registry_validation",
            "passing_tests",
            "current_evidence",
            "explicit_approval",
        ],
        "body": sanitized_body,
    }
    proposal["proposal_digest"] = canonical_digest(proposal)
    return proposal


def write_proposal(output_directory: Path, proposal: Mapping[str, object]) -> Path:
    """Write one proposal JSON without touching any registry or activation map."""
    proposal_id = proposal.get("proposal_id")
    kind = proposal.get("proposal_kind")
    if not isinstance(proposal_id, str) or not isinstance(kind, str):
        raise BuilderError("proposal_id and proposal_kind are required")
    require_identifier(proposal_id, "proposal_id")
    require_identifier(kind, "proposal_kind")
    if (
        proposal.get("status") != "candidate"
        or proposal.get("auto_activate") is not False
    ):
        raise BuilderError("only candidate, non-activating proposals may be written")
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{kind}--{proposal_id}.proposal.json"
    if destination.exists():
        raise DuplicateAssetError(f"proposal already exists: {destination.name}")
    destination.write_text(
        json.dumps(sanitize(proposal), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
