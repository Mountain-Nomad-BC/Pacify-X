"""Durable, secret-free Gremlin identity and recovery lifecycle audit sink."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from ..archive_io import reject_path_links
from ..engineering_os_paths import control_root
from ..event_ledger import append_chained_event
from ..json_io import bounded_canonical_json_bytes


_IDENTITY_EVENTS = frozenset(
    {
        "runtime_identity_created",
        "runtime_identity_rotated",
        "runtime_identity_revoked",
    }
)
_RECOVERY_EVENTS = frozenset(
    {
        "recovery_challenge_issued",
        "recovery_authorization_decided",
        "recovery_authorization_refused",
        "recovery_approval_revoked",
    }
)
_IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "authority_id",
        "identity_id",
        "generation",
        "occurred_at_utc",
        "result",
        "backend_id",
    }
)
_RECOVERY_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "recovery_authority_id",
        "challenge_id",
        "approval_id",
        "revocation_id",
        "protected_execution_id",
        "operation",
        "principal_id",
        "result",
        "occurred_at_utc",
    }
)


def _text(value: object, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError(f"Gremlin audit {name} must be bounded nonempty text")


def _timestamp(value: object) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError("Gremlin audit timestamp must be bounded nonempty text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Gremlin audit timestamp must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Gremlin audit timestamp must include a UTC offset")


class GremlinAuditLedger:
    """Callable audit sink backed by the repository's chained event ledger."""

    def __init__(self, root: Path) -> None:
        reject_path_links(Path(root))
        self.root = Path(root).resolve(strict=True)
        self.path = (
            control_root(self.root)
            / "runtime-core"
            / "gremlin"
            / "lifecycle-audit"
        )

    def __call__(self, event: Mapping[str, object]) -> Path:
        if not isinstance(event, Mapping):
            raise ValueError("Gremlin lifecycle audit event must be an object")
        image = dict(event)
        event_type = image.get("event_type")
        schema_version = image.get("schema_version")
        if isinstance(event_type, str) and event_type in _IDENTITY_EVENTS:
            expected = _IDENTITY_FIELDS
            if schema_version != "px.gremlin-runtime-identity-event/1.0":
                raise ValueError("Gremlin identity audit schema is unsupported")
            if type(image.get("generation")) is not int or image["generation"] < 1:
                raise ValueError("Gremlin identity audit generation is invalid")
            for name in ("authority_id", "identity_id", "result", "backend_id"):
                _text(image.get(name), name)
            kind = "gremlin_identity_lifecycle"
        elif isinstance(event_type, str) and event_type in _RECOVERY_EVENTS:
            expected = _RECOVERY_FIELDS
            if schema_version != "px.gremlin-recovery-event/1.0":
                raise ValueError("Gremlin recovery audit schema is unsupported")
            for name in ("recovery_authority_id", "protected_execution_id", "operation", "result"):
                _text(image.get(name), name)
            for name in ("challenge_id", "approval_id", "revocation_id", "principal_id"):
                _text(image.get(name), name, nullable=True)
            kind = "gremlin_recovery_lifecycle"
        else:
            raise ValueError("Gremlin lifecycle audit event type is unsupported")
        if set(image) != expected:
            raise ValueError("Gremlin lifecycle audit fields are not exact")
        _timestamp(image.get("occurred_at_utc"))
        bounded_canonical_json_bytes(image, max_bytes=16_384)
        reject_path_links(self.path)
        reject_path_links(
            self.path.parent / ".ledger-authority" / self.path.name
        )
        return append_chained_event(self.path, kind, image)
