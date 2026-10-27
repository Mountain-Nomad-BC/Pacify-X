"""Canonical semantic entity identity - implements punch card SEM-001.

The one rule this module exists to enforce
-----------------------------------------
An entity's identity is derived from stable intrinsic facts and NEVER from a
filesystem location. An entity renamed or moved keeps the same ``entity_id``.
Location is not identity, and this module refuses to let location leak into
identity.

That rule exists because the pre-existing mapping does the opposite.
``runtime/librarian_semantic_map.py`` derives registry entity ids from
path-shaped raw identifiers and stores ``source_path`` as a field ON the entity,
which fuses identity with location. A rename therefore produces a new identity
for the same thing, and every downstream consumer silently loses the link. That
is the duplication and loss of referential integrity SEM-002 through SEM-005
exist to repair, and it starts here.

Derived identity
----------------
``entity_id = "pxe1:" + sha256(canonical(identity_tuple))[:32]``

The ``identity_tuple`` is built from the identity basis, never from a path:

* ``intrinsic_name``      -> (kind, kind-specific intrinsic name)
* ``intrinsic_content``   -> (kind, sha256 of normalized content)
* ``declared_identifier`` -> (kind, declared identifier)
* ``structural_signature`` -> (kind, sha256 of a structural signature)

Each basis kind has its own required qualifier shape, enforced by
``identity_basis_for`` so a caller cannot accidentally derive identity from a
value that is not intrinsic.

Entity records
--------------
``EntityRecord`` carries identity, kind, basis, lifecycle and provenance. It has
**no path field at all**. A registry assigns identities and rejects two
different entities that claim the same id with different identity tuples, which
is the collision case SEM-001 calls out: if two declarations collide on
``intrinsic_name`` because they reuse a name, the correct answer is an explicit
error, never a silent winner.

Governance
----------
Lifecycle is proposed -> accepted -> retired and may never move backwards.
The registry rejects invalid transitions so a retired entity cannot silently
come back and a proposed one cannot be treated as accepted.
"""

from __future__ import annotations

from .secure_publish import atomic_write_bytes

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from runtime.json_io import bounded_canonical_json_bytes, decode_json_object

ENTITY_SCHEMA_VERSION = "px.semantic-entity/1.0"
ENTITY_SNAPSHOT_SCHEMA = "px.semantic-entity-snapshot/1.0"
MAX_SNAPSHOT_RECORDS = 100_000
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
ENTITY_ID_PREFIX = "pxe1:"
ENTITY_ID_DIGEST_LENGTH = 32
SCHEMA_RELATIVE = Path("contracts/semantic/semantic-entity.schema.json")

ENTITY_KINDS = (
    "declaration",
    "contract",
    "module",
    "operation",
    "symbol",
    "surface",
    "record",
    "artifact",
    "policy",
    "relation_kind",
)

IDENTITY_BASIS_KINDS = (
    "intrinsic_name",
    "intrinsic_content",
    "declared_identifier",
    "structural_signature",
)

LIFECYCLE_STATES = ("proposed", "accepted", "retired")
LIFECYCLE_TRANSITIONS = {
    "proposed": {"accepted", "retired"},
    "accepted": {"retired"},
    "retired": set(),
}


class SemanticEntityError(ValueError):
    """Raised when an entity or identity derivation is invalid."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_qualifier(basis_kind: str, qualifier: str) -> str:
    """Normalize a qualifier before it enters the identity digest."""
    if basis_kind not in IDENTITY_BASIS_KINDS:
        raise SemanticEntityError(f"identity basis kind is invalid: {basis_kind}")
    if not isinstance(qualifier, str):
        raise SemanticEntityError("identity qualifier must be a string")
    value = qualifier.strip()
    if not value:
        raise SemanticEntityError("identity qualifier must be a non-empty string")
    if len(value) > 512:
        raise SemanticEntityError("identity qualifier exceeds the semantic contract limit")
    if (any(ord(character) < 32 for character in value)
            or "/" in value or "\\" in value
            or (len(value) >= 2 and value[0].isalpha() and value[1] == ":")):
        raise SemanticEntityError("identity qualifier is a locator, not an intrinsic identifier")
    if basis_kind in {"intrinsic_name", "declared_identifier"}:
        # Names are case- and separator-normalized so a pure rename that only
        # changes casing or underscore style does not fork identity.
        normalized = "_".join(
            token for token in value.replace("-", "_").replace(".", "_").replace(" ", "_").lower().split("_") if token
        )
        if not normalized:
            raise SemanticEntityError("normalized identity qualifier is empty")
        return normalized
    if basis_kind == "intrinsic_content":
        # Content identity must already be a digest; hashing raw text here would
        # make identity depend on formatting.
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise SemanticEntityError(
                "intrinsic_content qualifier must be a 64 character lowercase sha256 digest"
            )
        return value
    return value


def identity_basis_for(basis_kind: str, qualifier: str, **extra: Any) -> dict[str, Any]:
    """Build identity inputs; audit lineage remains caller-owned metadata."""
    if basis_kind not in IDENTITY_BASIS_KINDS:
        raise SemanticEntityError(f"identity basis kind is invalid: {basis_kind}")
    basis: dict[str, Any] = {
        "basis_kind": basis_kind,
        "qualifier": normalize_qualifier(basis_kind, qualifier),
    }
    content = extra.get("content_sha256")
    if basis_kind == "intrinsic_content":
        if content is not None and content != basis["qualifier"]:
            raise SemanticEntityError("content digest contradicts the intrinsic identity qualifier")
        basis["content_sha256"] = basis["qualifier"]
    elif content is not None:
        raise SemanticEntityError(
            f"content_sha256 is only valid for intrinsic_content, not {basis_kind}"
        )
    return basis


def derive_entity_id(entity_kind: str, basis: Mapping[str, Any]) -> str:
    """Derive the content-addressed, path-independent entity id."""
    if entity_kind not in ENTITY_KINDS:
        raise SemanticEntityError(f"entity kind is invalid: {entity_kind}")
    basis_kind = str(basis.get("basis_kind") or "")
    qualifier = basis.get("qualifier")
    if not basis_kind or not qualifier:
        raise SemanticEntityError("identity basis requires a kind and a qualifier")
    identity_tuple = {
        "contract": ENTITY_SCHEMA_VERSION,
        "entity_kind": entity_kind,
        "basis_kind": basis_kind,
        "qualifier": normalize_qualifier(basis_kind, qualifier),
    }
    if basis_kind == "intrinsic_content":
        if basis.get("content_sha256") != identity_tuple["qualifier"]:
            raise SemanticEntityError("content digest contradicts the intrinsic identity qualifier")
        identity_tuple["content_sha256"] = basis["content_sha256"]
    return ENTITY_ID_PREFIX + _sha256(_canonical(identity_tuple))[:ENTITY_ID_DIGEST_LENGTH]


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity_id: str
    entity_kind: str
    identity_basis: Mapping[str, Any]
    lifecycle_state: str = "proposed"
    accepted_utc: str | None = None
    retired_utc: str | None = None
    retirement_reason: str | None = None
    declared_by: str = "unknown"
    observed_utc: str | None = None
    governing_contract: str | None = None
    notes: str | None = None
    terms: tuple[str, ...] = ()

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": ENTITY_SCHEMA_VERSION,
            "entity_id": self.entity_id,
            "entity_kind": self.entity_kind,
            "identity_basis": dict(self.identity_basis),
            "lifecycle": {
                "state": self.lifecycle_state,
                "accepted_utc": self.accepted_utc,
                "retired_utc": self.retired_utc,
                "retirement_reason": self.retirement_reason,
            },
            "provenance": {
                "declared_by": self.declared_by,
                "observed_utc": self.observed_utc,
                "governing_contract": self.governing_contract,
                "notes": self.notes,
            },
            "terms": list(self.terms),
        }


class EntityRegistry:
    """Assigns and holds canonical entity identities.

    The registry is the place where an identity COLLISION becomes explicit. Two
    declarations that derive the same id from different identity tuples are a
    real conflict, and the registry refuses rather than silently keeping one.
    """

    def __init__(self) -> None:
        self._entities: dict[str, EntityRecord] = {}
        self._basis_by_id: dict[str, dict[str, Any]] = {}

    def __len__(self) -> int:
        return len(self._entities)

    def __contains__(self, entity_id: object) -> bool:
        return str(entity_id) in self._entities

    def get(self, entity_id: str) -> EntityRecord | None:
        return self._entities.get(str(entity_id))

    def identity_tuple(self, entity_id: str) -> dict[str, Any] | None:
        value = self._basis_by_id.get(str(entity_id))
        return dict(value) if value is not None else None

    def all_entities(self) -> tuple[EntityRecord, ...]:
        return tuple(self._entities[key] for key in sorted(self._entities))

    def register(
        self,
        *,
        entity_kind: str,
        identity_basis: Mapping[str, Any],
        declared_by: str,
        observed_utc: str | None = None,
        governing_contract: str | None = None,
        notes: str | None = None,
        terms: Iterable[str] = (),
    ) -> EntityRecord:
        supplied_terms = tuple(terms)
        if (len(supplied_terms) > 256 or any(not isinstance(term, str)
                or not term.strip() or len(term) > 300 for term in supplied_terms)):
            raise SemanticEntityError("semantic search terms violate the entity contract")
        basis = dict(identity_basis)
        entity_id = derive_entity_id(entity_kind, basis)
        identity_tuple = {
            "entity_kind": entity_kind,
            "basis_kind": basis.get("basis_kind"),
            "qualifier": basis.get("qualifier"),
            "content_sha256": basis.get("content_sha256"),
        }
        existing = self._entities.get(entity_id)
        if existing is not None:
            prior = self._basis_by_id[entity_id]
            if prior != identity_tuple:
                raise SemanticEntityError(
                    "semantic entity identity collision: "
                    f"{entity_id} is claimed by {prior} and {identity_tuple}"
                )
            # Re-registering the identical entity is idempotent by design, so a
            # repeated scan converges rather than duplicating.
            return existing
        record = EntityRecord(
            entity_id=entity_id,
            entity_kind=entity_kind,
            identity_basis=MappingProxyType(basis),
            declared_by=declared_by,
            observed_utc=observed_utc,
            governing_contract=governing_contract,
            notes=notes,
            terms=tuple(sorted(set(supplied_terms))),
        )
        self._entities[entity_id] = record
        self._basis_by_id[entity_id] = identity_tuple
        return record

    def transition(
        self, entity_id: str, target_state: str, *, at_utc: str, reason: str | None = None
    ) -> EntityRecord:
        if target_state not in LIFECYCLE_STATES:
            raise SemanticEntityError(f"lifecycle state is invalid: {target_state}")
        record = self._entities.get(str(entity_id))
        if record is None:
            raise SemanticEntityError(f"unknown semantic entity: {entity_id}")
        allowed = LIFECYCLE_TRANSITIONS[record.lifecycle_state]
        if target_state not in allowed:
            raise SemanticEntityError(
                f"invalid lifecycle transition {record.lifecycle_state} -> {target_state}"
            )
        if target_state == "accepted":
            updated = replace(record, lifecycle_state="accepted", accepted_utc=at_utc)
        elif target_state == "retired":
            if not reason:
                raise SemanticEntityError("retirement requires a reason")
            updated = replace(
                record,
                lifecycle_state="retired",
                retired_utc=at_utc,
                retirement_reason=reason,
            )
        else:
            updated = replace(record, lifecycle_state="proposed")
        self._entities[str(entity_id)] = updated
        return updated

    def by_kind(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for record in self.all_entities():
            grouped.setdefault(record.entity_kind, []).append(record.entity_id)
        return {key: tuple(sorted(value)) for key, value in sorted(grouped.items())}

    def registry_document(self) -> dict[str, Any]:
        return {
            "schema_version": "px.semantic-entity-registry/1.0",
            "entity_contract": ENTITY_SCHEMA_VERSION,
            "contract_path": SCHEMA_RELATIVE.as_posix(),
            "entity_count": len(self._entities),
            "entities": [record.as_mapping() for record in self.all_entities()],
            "by_kind": {key: list(value) for key, value in self.by_kind().items()},
            "identity_rule": (
                "entity_id is derived from the identity basis only; no filesystem "
                "location participates in identity"
            ),
        }

    # ------------------------------------------------------------------
    # Durable canonical store
    # ------------------------------------------------------------------
    #
    # ``register`` and ``transition`` only hold state for the life of the
    # process, so an accepted identity cannot survive a restart and cannot be
    # proven to round-trip. The snapshot contract below mirrors the sibling
    # locator store exactly: bounded canonical JSON, a content digest over the
    # whole document, strict field and record validation, and re-derivation of
    # every identity from its own basis on recovery.
    #
    # The digest detects altered content. It is NOT an authenticity proof, and
    # recovery is metadata only: it never creates an identity that was not
    # already present and never grants lifecycle authority to a caller.

    def snapshot_bytes(self) -> bytes:
        """Export actual metadata for owned persistence, never lifecycle authority."""
        if len(self._entities) > MAX_SNAPSHOT_RECORDS:
            raise SemanticEntityError("entity snapshot record budget exhausted")
        body = {
            "schema_version": ENTITY_SNAPSHOT_SCHEMA,
            "entity_contract": ENTITY_SCHEMA_VERSION,
            "records": [record.as_mapping() for record in self.all_entities()],
        }
        try:
            image = bounded_canonical_json_bytes(body, max_bytes=MAX_SNAPSHOT_BYTES)
            return bounded_canonical_json_bytes(
                {**body, "content_sha256": hashlib.sha256(image).hexdigest()},
                max_bytes=MAX_SNAPSHOT_BYTES,
            )
        except ValueError as exc:
            raise SemanticEntityError(str(exc)) from exc

    @classmethod
    def from_snapshot_bytes(cls, raw: bytes) -> "EntityRegistry":
        """Recover only complete, validated records whose identities re-derive.

        The digest detects altered content; it is not an authenticity proof.
        Persistence admission and lifecycle authority belong to callers. A
        record whose stored ``entity_id`` does not re-derive from its own
        identity basis is refused, so a tampered identity can never enter a
        recovered registry.
        """
        from runtime.contracts import validate_instance

        if type(raw) is not bytes:
            raise SemanticEntityError("entity snapshot must be an exact byte image")
        try:
            document = decode_json_object(raw, max_bytes=MAX_SNAPSHOT_BYTES)
            if set(document) != {
                "schema_version", "entity_contract", "records", "content_sha256",
            }:
                raise SemanticEntityError("entity snapshot fields are invalid")
            digest = document.pop("content_sha256")
            if document["schema_version"] != ENTITY_SNAPSHOT_SCHEMA:
                raise SemanticEntityError("entity snapshot schema is unsupported")
            if document["entity_contract"] != ENTITY_SCHEMA_VERSION:
                raise SemanticEntityError("entity snapshot contract version is unsupported")
            if type(digest) is not str or digest != hashlib.sha256(
                bounded_canonical_json_bytes(document, max_bytes=MAX_SNAPSHOT_BYTES)
            ).hexdigest():
                raise SemanticEntityError("entity snapshot content digest mismatch")
            records = document["records"]
            if type(records) is not list or len(records) > MAX_SNAPSHOT_RECORDS:
                raise SemanticEntityError("entity snapshot record budget is invalid")

            recovered = cls()
            previous_id = None
            for row in records:
                validate_instance(
                    row, Path(__file__).resolve().parents[1] / SCHEMA_RELATIVE
                )
                entity_id = row["entity_id"]
                if type(entity_id) is not str or not entity_id.startswith(ENTITY_ID_PREFIX):
                    raise SemanticEntityError("entity snapshot record has no canonical identity")
                # Records are emitted in sorted id order, so a duplicate or
                # out-of-order identity cannot be absorbed silently.
                if previous_id is not None and entity_id <= previous_id:
                    raise SemanticEntityError("entity snapshot records must be uniquely ordered")
                previous_id = entity_id
                lifecycle = row["lifecycle"]
                state = lifecycle["state"]
                if state not in LIFECYCLE_STATES:
                    raise SemanticEntityError("entity snapshot lifecycle state is invalid")
                if state != "proposed" and not lifecycle.get("accepted_utc"):
                    raise SemanticEntityError("entity snapshot accepted record requires acceptance time")
                if state == "retired" and (
                    not lifecycle.get("retired_utc") or not lifecycle.get("retirement_reason")
                ):
                    raise SemanticEntityError("entity snapshot retired record requires a reason")
                basis = row["identity_basis"]
                expected = derive_entity_id(row["entity_kind"], basis)
                if expected != entity_id:
                    raise SemanticEntityError("entity snapshot identity binding mismatch")
                record = EntityRecord(
                    entity_id=entity_id,
                    entity_kind=row["entity_kind"],
                    identity_basis=MappingProxyType(dict(basis)),
                    lifecycle_state=state,
                    accepted_utc=lifecycle.get("accepted_utc"),
                    retired_utc=lifecycle.get("retired_utc"),
                    retirement_reason=lifecycle.get("retirement_reason"),
                    declared_by=row["provenance"]["declared_by"],
                    observed_utc=row["provenance"].get("observed_utc"),
                    governing_contract=row["provenance"].get("governing_contract"),
                    notes=row["provenance"].get("notes"),
                    terms=tuple(row["terms"]),
                )
                recovered._entities[entity_id] = record
                recovered._basis_by_id[entity_id] = {
                    "entity_kind": row["entity_kind"],
                    "basis_kind": basis.get("basis_kind"),
                    "qualifier": basis.get("qualifier"),
                    "content_sha256": basis.get("content_sha256"),
                }
            return recovered
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SemanticEntityError(f"invalid entity snapshot: {exc}") from exc

    def accepted_entities(self) -> tuple[EntityRecord, ...]:
        """Only accepted identities; retired and proposed records are not accepted."""
        return tuple(
            record for record in self.all_entities() if record.lifecycle_state == "accepted"
        )

    def assert_unique_accepted(self) -> tuple[str, ...]:
        """Prove the W1 exit condition of zero duplicate accepted canonical IDs.

        The registry already keys by identity, so duplication can only arise
        from a corrupted or hand-built recovery. This checks it explicitly
        rather than assuming the invariant, and never merges a duplicate.
        """
        seen: dict[str, EntityRecord] = {}
        duplicates: list[str] = []
        for record in self.accepted_entities():
            if record.entity_id in seen:
                if seen[record.entity_id].identity_basis != dict(record.identity_basis):
                    duplicates.append(record.entity_id)
                continue
            seen[record.entity_id] = record
        if duplicates:
            raise SemanticEntityError(
                "duplicate accepted canonical identities: " + ", ".join(sorted(duplicates))
            )
        return tuple(sorted(seen))

    def resolve_declared_identifier(self, entity_kind: str, identifier: str) -> tuple[EntityRecord, ...]:
        """Reverse-resolve by a declared identifier without falling back to paths.

        Returns every matching record rather than guessing a winner, so genuine
        ambiguity stays visible to the caller instead of being silently
        assigned. The qualifier is normalized exactly as it was at registration,
        so ``kept.contract`` resolves the same stored ``kept_contract``.
        """
        if entity_kind not in ENTITY_KINDS or type(identifier) is not str or not identifier.strip():
            raise SemanticEntityError("declared identifier resolution requires a valid kind and value")
        wanted = normalize_qualifier("declared_identifier", identifier)
        return tuple(
            record
            for record in self.accepted_entities()
            if record.entity_kind == entity_kind
            and record.identity_basis.get("basis_kind") == "declared_identifier"
            and str(record.identity_basis.get("qualifier", "")).casefold() == wanted.casefold()
        )
# ----------------------------------------------------------------------
# Durable publication of the accepted canonical registry
# ----------------------------------------------------------------------
#
# The registry is only useful to other processes once its accepted identities
# survive a restart. Publication writes the exact snapshot bytes under the
# engineering-OS runtime-core semantic directory using the same
# content-addressed, fsynced, atomic-replacement convention used elsewhere in
# the runtime. Publication never grants lifecycle authority: it stores
# metadata, and recovery re-derives every identity from its own basis.

PUBLISHED_REGISTRY_RELATIVE = Path(
    ".agentic_engineering_os_px/runtime-core/semantic/entity-registry.json"
)


def published_registry_path(root: Path) -> Path:
    return Path(root) / PUBLISHED_REGISTRY_RELATIVE


def publish_registry(registry: "EntityRegistry", root: Path) -> dict[str, Any]:
    """Persist the accepted canonical registry durably and return a receipt.

    The write is fsynced and atomically replaced. An identical prior image is
    left untouched (idempotent republication) rather than rewritten, so repeated
    scans do not churn the file or its mtime.
    """
    from runtime.file_lock import FileLock
    from runtime.json_io import read_bounded_bytes

    if type(registry) is not EntityRegistry:
        raise SemanticEntityError("publication requires the canonical entity registry")
    root = Path(root).resolve(strict=True)
    target = published_registry_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = registry.snapshot_bytes()
    digest = hashlib.sha256(image).hexdigest()
    with FileLock(target.parent / ".entity-registry.lock", timeout_seconds=10):
        existing = None
        if target.is_file():
            existing = bytes(read_bounded_bytes(target, max_bytes=MAX_SNAPSHOT_BYTES))
        if existing == image:
            return {
                "schema_version": "px.semantic-entity-publication/1.0",
                "status": "UNCHANGED",
                "path": PUBLISHED_REGISTRY_RELATIVE.as_posix(),
                "entity_count": len(registry),
                "content_sha256": digest,
                "authority_granted": False,
            }
        atomic_write_bytes(target, image)
    return {
        "schema_version": "px.semantic-entity-publication/1.0",
        "status": "PUBLISHED",
        "path": PUBLISHED_REGISTRY_RELATIVE.as_posix(),
        "entity_count": len(registry),
        "content_sha256": digest,
        "authority_granted": False,
    }


def load_published_registry(root: Path) -> "EntityRegistry | None":
    """Load the durable accepted registry, or None when nothing is published.

    A corrupt or tampered published image raises rather than being ignored, so
    an invalid registry cannot masquerade as "no publication".
    """
    from runtime.json_io import read_bounded_bytes

    root = Path(root).resolve(strict=True)
    target = published_registry_path(root)
    if not target.is_file():
        return None
    return EntityRegistry.from_snapshot_bytes(bytes(read_bounded_bytes(target, max_bytes=MAX_SNAPSHOT_BYTES)))