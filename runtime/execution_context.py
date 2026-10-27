"""Small execution identity/currentness envelope; never a grant of authority."""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re

from .json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.execution-context/1.0"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    execution_id: str
    parent_execution_id: str | None
    root_execution_id: str
    project_id: str
    session_id: str
    revision: int
    epoch: int
    generation_vector_sha256: str | None
    authority_reference_sha256: str
    effect_budget_sha256: str
    cancellation_scope_id: str
    deadline_utc: str
    actor_id: str
    provider_id: str | None
    trace_root_id: str
    # Canonical lineage and control references (Rev1.xx finish plan Phase 1B).
    # Each is an OPTIONAL exact SHA256 identity; None means "not applicable for
    # this execution", which is distinct from an absent field because the field
    # is always serialized. These bind an execution to the exact revisions and
    # control records it ran under, so a stale result cannot be replayed into a
    # newer generation.
    model_execution_group_revision: str | None = None
    contract_set_revision: str | None = None
    gremlin_revision: str | None = None
    network_policy_revision: str | None = None
    workflow_adapter_revision: str | None = None
    lease_id: str | None = None
    effect_intent_id: str | None = None

    #: Fields whose value (when present) must be an exact lowercase SHA256.
    _DIGEST_FIELDS = (
        "generation_vector_sha256", "authority_reference_sha256", "effect_budget_sha256",
        "model_execution_group_revision", "contract_set_revision", "gremlin_revision",
        "network_policy_revision", "workflow_adapter_revision",
    )
    #: Optional bounded-text control identities (lease/effect-intent are records
    #: whose identity is an opaque bounded id, not necessarily a digest).
    _CONTROL_ID_FIELDS = ("lease_id", "effect_intent_id")

    def __post_init__(self):
        for field in ("execution_id", "root_execution_id", "project_id", "session_id", "cancellation_scope_id", "actor_id", "trace_root_id"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value):
                raise ValueError("execution identity must be bounded nonempty text")
        for field in ("parent_execution_id", "provider_id"):
            value = getattr(self, field)
            if value is not None and (type(value) is not str or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value)):
                raise ValueError("invalid optional execution identity")
        for field in ("revision", "epoch"):
            if type(getattr(self, field)) is not int or not 1 <= getattr(self, field) <= 2147483647:
                raise ValueError("execution revision/epoch must be positive bounded integers")
        for field in ("generation_vector_sha256", "authority_reference_sha256", "effect_budget_sha256"):
            value = getattr(self, field)
            if field == "generation_vector_sha256" and value is None: continue
            if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError("execution references must be exact SHA256 identities")
        for field in self._DIGEST_FIELDS:
            value = getattr(self, field)
            if value is None:
                continue
            if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError(f"execution lineage reference {field} must be an exact SHA256 identity")
        for field in self._CONTROL_ID_FIELDS:
            value = getattr(self, field)
            if value is not None and (type(value) is not str or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value)):
                raise ValueError(f"execution control identity {field} must be bounded nonempty text")
        if self.parent_execution_id is None and self.root_execution_id != self.execution_id:
            raise ValueError("root execution must identify itself")
        if self.parent_execution_id == self.execution_id:
            raise ValueError("execution cannot parent itself")
        if self.parent_execution_id is not None and self.root_execution_id == self.execution_id:
            raise ValueError("child execution cannot claim root identity")
        if type(self.deadline_utc) is not str or len(self.deadline_utc) > 64:
            raise ValueError("execution deadline must be bounded timestamp text")
        moment = datetime.fromisoformat(self.deadline_utc.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("execution deadline must be timezone-aware")

    def _body(self):
        return {"schema_version": SCHEMA_VERSION, **asdict(self), "authority_granted": False}

    @property
    def context_sha256(self):
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=16384)).hexdigest()

    def as_dict(self):
        return {**self._body(), "context_sha256": self.context_sha256}

    def assert_current(self, *, project_id, session_id, epoch, generation_vector_sha256=None, now=None):
        if (project_id != self.project_id or session_id != self.session_id or epoch != self.epoch
                or generation_vector_sha256 != self.generation_vector_sha256):
            raise ValueError("execution context identity/currentness differs")
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None or moment >= datetime.fromisoformat(self.deadline_utc.replace("Z", "+00:00")):
            raise ValueError("execution deadline expired or observation is naive")

    def child(self, execution_id, *, provider_id=None, deadline_utc=None):
        deadline = deadline_utc or self.deadline_utc
        if datetime.fromisoformat(deadline.replace("Z", "+00:00")) > datetime.fromisoformat(self.deadline_utc.replace("Z", "+00:00")):
            raise ValueError("child cannot extend parent deadline")
        return replace(self, execution_id=execution_id, parent_execution_id=self.execution_id,
                       provider_id=provider_id, deadline_utc=deadline)


def execution_context_from_dict(value):
    if type(value) is not dict or value.get("schema_version") != SCHEMA_VERSION or value.get("authority_granted") is not False:
        raise ValueError("typed non-authoritative execution context required")
    from .contracts import validate_instance
    validate_instance(value, Path(__file__).resolve().parents[1] / "contracts/execution-context.schema.json")
    context = ExecutionContext(**{k: v for k, v in value.items() if k not in {"schema_version", "authority_granted", "context_sha256"}})
    if value["context_sha256"] != context.context_sha256:
        raise ValueError("execution context digest differs")
    return context
