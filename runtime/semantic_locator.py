"""Locator and relation separation - implements punch card SEM-002.

Two separations, one idea
-------------------------
SEM-001 established that identity is intrinsic and location is not. SEM-002
makes that structural rather than merely conventional, by giving location and
graph edges their OWN record types:

* :class:`LocatorRecord` binds an ``entity_id`` to where it currently lives.
  Relocating an entity replaces its locator. The ``entity_id`` is never touched,
  which is exactly the property SEM-001 promised and this module enforces.
* :class:`RelationRecord` binds two ``entity_id`` values with a typed edge. A
  relation is a first-class record, so neither endpoint needs to know the edge
  exists, and retiring an endpoint is a decision the graph can see.

Why this was necessary
----------------------
The pre-existing bridge does the opposite. ``runtime/semantic_project_map_bridge.py``
builds ``locator = path`` as an inline string with no entity binding, and its
``stable_id`` folds in the project map ``revision``, so a locator's identity
moves whenever the map revision does. Location and identity are entangled there
in a way that makes rename detection impossible.

Dangling endpoints
------------------
A relation is refused unless both endpoints resolve to live entities. This is
enforced at registration AND re-checked on read, so an endpoint retired later
turns into a reported dangling relation rather than a silently broken edge. A
``located_at`` edge is derived from locators, never asserted independently, so
it can never contradict the locator it claims to reflect.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from runtime.json_io import bounded_canonical_json_bytes, decode_json_object

from runtime.semantic_entity import (
    ENTITY_ID_PREFIX,
    EntityRegistry,
    SemanticEntityError,
)

LOCATOR_SCHEMA_VERSION = "px.semantic-locator/2.0"
RELATION_SCHEMA_VERSION = "px.semantic-relation/1.0"
LOCATOR_ID_PREFIX = "pxl1:"
RELATION_ID_PREFIX = "pxr1:"
SCHEMA_LOCATOR = Path("contracts/semantic/locator-record.schema.json")
SCHEMA_RELATION = Path("contracts/semantic/relation-record.schema.json")
LOCATOR_SNAPSHOT_SCHEMA = "px.semantic-locator-snapshot/1.0"
MAX_SNAPSHOT_RECORDS = 10_000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024

LOCATOR_KINDS = ("file", "directory", "line_range", "symbol", "uri", "external")

RELATION_KINDS = (
    "defines",
    "depends_on",
    "implements",
    "calls",
    "imports",
    "extends",
    "owns",
    "located_at",
    "references",
    "contradicts",
    "supersedes",
)

# Edge kinds that must never point outside the entity graph.
GRAPH_ONLY_RELATIONS = frozenset(
    {"defines", "depends_on", "implements", "calls", "imports", "extends", "supersedes"}
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_id(prefix: str, value: Any) -> str:
    return prefix + hashlib.sha256(_canonical(value)).hexdigest()[:32]


class SemanticLocatorError(ValueError):
    """Raised when a locator or relation record is invalid."""


def _portable_parts(reference: str, *, root: bool = False) -> tuple[str, ...]:
    if root and reference == "":
        return ()
    if (type(reference) is not str or not reference or len(reference) > 1024
            or reference.startswith("/") or "\\" in reference or ":" in reference
            or any(ord(char) < 32 or ord(char) == 127 for char in reference)):
        raise SemanticLocatorError("locator path must be portable and repository-relative")
    parts = tuple(reference.split("/"))
    for part in parts:
        if (part in {"", ".", ".."} or part.rstrip(" .") != part
                or any(char in '<>"|?*' for char in part)
                or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", part.split(".")[0], re.I)):
            raise SemanticLocatorError("locator path contains an unsafe or ambiguous component")
    return parts


def _uri_parts(reference: str) -> tuple[str, str, tuple[str, ...]]:
    if type(reference) is not str or not reference or len(reference) > 1024 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in reference):
        raise SemanticLocatorError("locator URI must be bounded canonical text")
    try:
        parsed = urlsplit(reference)
        # Force validation of malformed ports and IPv6 authorities as well.
        parsed.port
        if not parsed.scheme or not parsed.netloc or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("URI requires a scheme and credential-free authority")
        decoded = unquote(parsed.path)
        if "\\" in reference or "//" in parsed.path or "%" in decoded or re.search(r"%2f|%5c", parsed.path, re.I):
            raise ValueError("URI path contains ambiguous encoding")
        parts = tuple(decoded.removeprefix("/").rstrip("/").split("/")) if decoded not in {"", "/"} else ()
        if any(part in {"", ".", ".."} or any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts):
            raise ValueError("URI path contains unsafe components")
        return parsed.scheme.lower(), parsed.netloc.lower(), parts
    except ValueError as exc:
        raise SemanticLocatorError(f"invalid locator URI: {exc}") from exc


@dataclass(frozen=True, slots=True)
class LocatorReferencePolicy:
    """Lexical metadata namespaces; grants no filesystem or network effects.

    An empty root denotes the portable repository namespace. External references
    require explicit current caller configuration, never a snapshot declaration.
    """
    allowed_roots: tuple[str, ...] = ("",)
    uri_roots: tuple[str, ...] = ()
    external_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (self.allowed_roots, self.uri_roots, self.external_prefixes):
            if type(field) is not tuple or len(field) > 128 or any(type(value) is not str for value in field) or len(set(field)) != len(field):
                raise SemanticLocatorError("locator namespaces must be bounded unique string tuples")
        for root in self.allowed_roots:
            _portable_parts(root, root=True)
        for root in self.uri_roots:
            _uri_parts(root)
            parsed = urlsplit(root)
            if parsed.query or parsed.fragment:
                raise SemanticLocatorError("URI namespace roots cannot contain queries or fragments")
        for prefix in self.external_prefixes:
            if len(prefix) > 200 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*(?::[A-Za-z][A-Za-z0-9_.-]*)*:", prefix):
                raise SemanticLocatorError("external namespace prefix must end at a declared colon boundary")

    def validate(self, kind: str, reference: str) -> None:
        if kind == "uri":
            scheme, authority, parts = _uri_parts(reference)
            for root in self.uri_roots:
                root_scheme, root_authority, root_parts = _uri_parts(root)
                if (scheme, authority) == (root_scheme, root_authority) and parts[:len(root_parts)] == root_parts:
                    return
        elif kind == "external":
            if type(reference) is str and len(reference) <= 1024 and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in reference):
                if any(reference.startswith(prefix) and len(reference) > len(prefix) for prefix in self.external_prefixes):
                    return
        elif kind in LOCATOR_KINDS:
            parts = _portable_parts(reference)
            if any(parts[:len(root_parts)] == root_parts for root_parts in (_portable_parts(root, root=True) for root in self.allowed_roots)):
                return
        raise SemanticLocatorError("locator reference is outside current declared roots/namespaces")


@dataclass(frozen=True, slots=True)
class LocatorRecord:
    locator_id: str
    entity_id: str
    locator_kind: str
    reference: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    observed_utc: str | None = None
    observed_by: str | None = None
    confidence: float | None = None
    revision: int = 1

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": LOCATOR_SCHEMA_VERSION,
            "locator_id": self.locator_id,
            "entity_id": self.entity_id,
            "locator_kind": self.locator_kind,
            "revision": self.revision,
            "location": {
                "reference": self.reference,
                "line_start": self.line_start,
                "line_end": self.line_end,
                "symbol": self.symbol,
            },
            "observed_utc": self.observed_utc,
            "observed_by": self.observed_by,
            "confidence": self.confidence,
        }


def derive_locator_id(entity_id: str, locator_kind: str, reference: str, *,
                      line_start: int | None = None, line_end: int | None = None,
                      symbol: str | None = None, revision: int = 1) -> str:
    """Bind complete location geometry and revision, never change entity identity."""
    if locator_kind not in LOCATOR_KINDS:
        raise SemanticLocatorError(f"locator kind is invalid: {locator_kind}")
    if type(entity_id) is not str or not re.fullmatch(r"pxe1:[0-9a-f]{32}", entity_id):
        raise SemanticLocatorError("locator requires a canonical entity_id")
    if type(reference) is not str or not reference.strip() or len(reference) > 1024:
        raise SemanticLocatorError("locator reference must be a non-empty string")
    if type(revision) is not int or not 1 <= revision <= 2147483647:
        raise SemanticLocatorError("locator revision must be a positive bounded integer")
    for value in (line_start, line_end):
        if value is not None and (type(value) is not int or not 1 <= value <= 2147483647):
            raise SemanticLocatorError("locator lines must be positive bounded integers")
    if line_start is not None and line_end is not None and line_start > line_end:
        raise SemanticLocatorError("locator line_start exceeds line_end")
    if locator_kind == "line_range" and (line_start is None or line_end is None):
        raise SemanticLocatorError("line_range locator requires line_start and line_end")
    if symbol is not None and (type(symbol) is not str or len(symbol) > 400):
        raise SemanticLocatorError("locator symbol must be bounded text")
    return _digest_id(
        LOCATOR_ID_PREFIX,
        {
            "contract": LOCATOR_SCHEMA_VERSION,
            "entity_id": str(entity_id),
            "locator_kind": locator_kind,
            "reference": str(reference),
            "line_start": line_start,
            "line_end": line_end,
            "symbol": symbol,
            "revision": revision,
        },
    )


class LocatorRegistry:
    """Holds the current location of each entity.

    There is at most ONE current locator per (entity, locator_kind). Relocating
    an entity supersedes its previous immutable revision. History is retained
    as actual observations, separately from current-only resolution.
    """

    def __init__(self, entities: EntityRegistry, *, max_history: int = 64,
                 reference_policy: LocatorReferencePolicy | None = None) -> None:
        if type(max_history) is not int or not 1 <= max_history <= 4096:
            raise SemanticLocatorError("locator history limit must be a positive bounded integer")
        self._entities = entities
        self._locators: dict[tuple[str, str], LocatorRecord] = {}
        self._history: dict[tuple[str, str], tuple[LocatorRecord, ...]] = {}
        self._max_history = max_history
        if reference_policy is not None and type(reference_policy) is not LocatorReferencePolicy:
            raise SemanticLocatorError("locator reference policy must be a typed current policy")
        self._reference_policy = reference_policy if reference_policy is not None else LocatorReferencePolicy()

    def __len__(self) -> int:
        return len(self._locators)

    def metadata_copy(self) -> "LocatorRegistry":
        """Independent current metadata using this owner's exact namespace policy."""
        return type(self).from_snapshot_bytes(self._entities, self.snapshot_bytes(),
                                             reference_policy=self._reference_policy)

    @property
    def entity_snapshot_sha256(self) -> str:
        return hashlib.sha256(self._entities.snapshot_bytes()).hexdigest()

    def set_locator(
        self,
        *,
        entity_id: str,
        locator_kind: str,
        reference: str,
        line_start: int | None = None,
        line_end: int | None = None,
        symbol: str | None = None,
        observed_utc: str | None = None,
        observed_by: str | None = None,
        confidence: float | None = None,
    ) -> LocatorRecord:
        record = self._entities.get(entity_id)
        if record is None:
            raise SemanticLocatorError(
                f"locator references an unknown entity: {entity_id}"
            )
        if record.lifecycle_state == "retired":
            raise SemanticLocatorError(
                f"cannot locate a retired entity: {entity_id}"
            )
        self._reference_policy.validate(locator_kind, reference)
        # Validate before comparing with the current record: bools compare equal
        # to integers and must never bypass geometry validation on an exact hit.
        derive_locator_id(entity_id, locator_kind, reference, line_start=line_start,
                          line_end=line_end, symbol=symbol)
        if confidence is not None and (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0):
            raise SemanticLocatorError("locator confidence must be between 0 and 1")
        if observed_by is not None and (type(observed_by) is not str or len(observed_by) > 200):
            raise SemanticLocatorError("locator observer must be bounded text")
        if observed_utc is not None:
            try:
                if type(observed_utc) is not str or datetime.fromisoformat(observed_utc.replace("Z", "+00:00")).utcoffset() is None:
                    raise ValueError("Observation requires a timezone")
            except (TypeError, ValueError) as exc:
                raise SemanticLocatorError("locator observation must be an actual timezone-aware timestamp") from exc
        previous = self._locators.get((entity_id, locator_kind))
        candidate = (reference, line_start, line_end, symbol, observed_utc, observed_by, confidence)
        if previous is not None and candidate == (previous.reference, previous.line_start, previous.line_end, previous.symbol,
                                                 previous.observed_utc, previous.observed_by, previous.confidence):
            return previous
        history = self._history.get((entity_id, locator_kind), ())
        if len(history) >= self._max_history:
            raise SemanticLocatorError("locator history budget exhausted; explicit archival disposition required")
        revision = previous.revision + 1 if previous else 1
        locator = LocatorRecord(
            locator_id=derive_locator_id(entity_id, locator_kind, reference, line_start=line_start,
                                         line_end=line_end, symbol=symbol, revision=revision),
            entity_id=entity_id,
            locator_kind=locator_kind,
            reference=str(reference),
            line_start=line_start,
            line_end=line_end,
            symbol=symbol,
            observed_utc=observed_utc,
            observed_by=observed_by,
            confidence=confidence,
            revision=revision,
        )
        self._locators[(entity_id, locator_kind)] = locator
        self._history[(entity_id, locator_kind)] = history + (locator,)
        return locator

    def get(self, entity_id: str, locator_kind: str) -> LocatorRecord | None:
        entity = self._entities.get(str(entity_id))
        if entity is None or entity.lifecycle_state == "retired":
            return None
        return self._locators.get((str(entity_id), str(locator_kind)))

    def history(self, entity_id: str, locator_kind: str) -> tuple[LocatorRecord, ...]:
        """Historical metadata only; never an execution/current resolver."""
        return self._history.get((str(entity_id), str(locator_kind)), ())

    def all_history(self) -> tuple[LocatorRecord, ...]:
        """Complete retained metadata, including superseded and retired records."""
        return tuple(record for key in sorted(self._history) for record in self._history[key])

    def snapshot_bytes(self) -> bytes:
        """Export actual metadata for owned persistence, never lifecycle authority."""
        if sum(map(len, self._history.values())) > MAX_SNAPSHOT_RECORDS:
            raise SemanticLocatorError("locator snapshot record budget exhausted")
        body = {"schema_version": LOCATOR_SNAPSHOT_SCHEMA, "max_history": self._max_history,
                "records": [record.as_mapping() for key in sorted(self._history)
                            for record in self._history[key]]}
        try:
            image = bounded_canonical_json_bytes(body, max_bytes=MAX_SNAPSHOT_BYTES)
            return bounded_canonical_json_bytes({**body, "content_sha256": hashlib.sha256(image).hexdigest()},
                                                max_bytes=MAX_SNAPSHOT_BYTES)
        except ValueError as exc:
            raise SemanticLocatorError(str(exc)) from exc

    @classmethod
    def from_snapshot_bytes(cls, entities: EntityRegistry, raw: bytes, *,
                            reference_policy: LocatorReferencePolicy | None = None) -> LocatorRegistry:
        """Recover only complete, validated history against a current entity owner.

        The digest detects altered content; it is not an authenticity proof.
        Persistence admission, provenance authority and lifecycle belong to callers.
        No supplied entity can be created or promoted by this metadata operation.
        """
        from runtime.contracts import validate_instance

        if type(raw) is not bytes:
            raise SemanticLocatorError("locator snapshot must be an exact byte image")
        try:
            document = decode_json_object(raw, max_bytes=MAX_SNAPSHOT_BYTES)
            if set(document) != {"schema_version", "max_history", "records", "content_sha256"}:
                raise SemanticLocatorError("locator snapshot fields are invalid")
            digest = document.pop("content_sha256")
            if document["schema_version"] != LOCATOR_SNAPSHOT_SCHEMA:
                raise SemanticLocatorError("locator snapshot schema is unsupported")
            if type(digest) is not str or digest != hashlib.sha256(
                    bounded_canonical_json_bytes(document, max_bytes=MAX_SNAPSHOT_BYTES)).hexdigest():
                raise SemanticLocatorError("locator snapshot content digest mismatch")
            records = document["records"]
            if type(records) is not list or len(records) > MAX_SNAPSHOT_RECORDS:
                raise SemanticLocatorError("locator snapshot record budget is invalid")
            recovered = cls(entities, max_history=document["max_history"], reference_policy=reference_policy)
            previous_order = None
            for row in records:
                validate_instance(row, Path(__file__).resolve().parents[1] / SCHEMA_LOCATOR)
                identifier, kind = row["entity_id"], row["locator_kind"]
                if entities.get(identifier) is None:
                    raise SemanticLocatorError("locator snapshot references an unknown entity")
                location = row["location"]
                recovered._reference_policy.validate(kind, location["reference"])
                key = (identifier, kind)
                order = (*key, row["revision"])
                if previous_order is not None and order <= previous_order:
                    raise SemanticLocatorError("locator snapshot records must be uniquely ordered")
                previous_order = order
                history = recovered._history.get(key, ())
                if row["revision"] != len(history) + 1 or len(history) >= recovered._max_history:
                    raise SemanticLocatorError("locator snapshot history is incomplete or exceeds its budget")
                expected = derive_locator_id(identifier, kind, location["reference"],
                    line_start=location.get("line_start"), line_end=location.get("line_end"),
                    symbol=location.get("symbol"), revision=row["revision"])
                if row["locator_id"] != expected:
                    raise SemanticLocatorError("locator snapshot geometry binding mismatch")
                timestamp = row.get("observed_utc")
                if timestamp is not None and datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset() is None:
                    raise SemanticLocatorError("locator snapshot observation requires a timezone")
                record = LocatorRecord(expected, identifier, kind, location["reference"],
                    line_start=location.get("line_start"), line_end=location.get("line_end"),
                    symbol=location.get("symbol"), observed_utc=timestamp,
                    observed_by=row.get("observed_by"), confidence=row.get("confidence"), revision=row["revision"])
                recovered._history[key] = history + (record,)
                recovered._locators[key] = record
            return recovered
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SemanticLocatorError(f"invalid locator snapshot: {exc}") from exc

    def resolve_reference(self, locator_kind: str, reference: str) -> tuple[LocatorRecord, ...]:
        if locator_kind not in LOCATOR_KINDS or type(reference) is not str or not reference.strip() or len(reference) > 1024:
            raise SemanticLocatorError("reverse resolution requires a valid kind and bounded exact reference")
        self._reference_policy.validate(locator_kind, reference)
        return tuple(record for record in self.all_locators()
                     if record.locator_kind == locator_kind and record.reference == reference)

    def resolve_any(self, locator_kind: str, reference: str) -> dict[str, object]:
        """Dual locator resolver: resolve a reference to canonical identity.

        MIG-002 requires that during a migration window both the OLD and the NEW
        path resolve to the same canonical entity, while new writes target only
        the current canonical locator. This returns the canonical ``entity_id``
        plus an explicit ``resolved_as`` classification so a caller can tell a
        current locator from a historical one:

        * ``current``     - the reference is the entity's current locator;
        * ``historical``  - the reference is a retained past locator;
        * ``unresolved``  - no locator (current or historical) matches.

        Ambiguous historical matches (two entities once shared a path) are
        reported explicitly rather than resolved to an arbitrary winner.
        """
        if locator_kind not in LOCATOR_KINDS or type(reference) is not str or not reference.strip() or len(reference) > 1024:
            raise SemanticLocatorError("dual resolution requires a valid kind and bounded exact reference")
        self._reference_policy.validate(locator_kind, reference)
        current = self.resolve_reference(locator_kind, reference)
        if current:
            return {"resolved_as": "current" if len(current) == 1 else "ambiguous",
                    "entity_ids": sorted({record.entity_id for record in current}),
                    "locator_kind": locator_kind, "reference": reference}
        historical: dict[str, LocatorRecord] = {}
        for record in self.all_locators():
            if record.locator_kind != locator_kind:
                continue
            for past in self.history(record.entity_id, locator_kind):
                if past.reference == reference:
                    historical[record.entity_id] = past
        return {"resolved_as": "historical" if len(historical) == 1 else
                "ambiguous" if len(historical) > 1 else "unresolved",
                "entity_ids": sorted(historical), "locator_kind": locator_kind,
                "reference": reference}

    def resolve_locator(self, locator_id: str) -> LocatorRecord | None:
        return next((record for record in self.all_locators() if record.locator_id == locator_id), None)

    def for_entity(self, entity_id: str) -> tuple[LocatorRecord, ...]:
        return tuple(
            self._locators[key]
            for key in sorted(self._locators)
            if key[0] == str(entity_id) and self.get(*key) is not None
        )

    def all_locators(self) -> tuple[LocatorRecord, ...]:
        return tuple(self._locators[key] for key in sorted(self._locators) if self.get(*key) is not None)

    def relocate(self, entity_id: str, new_reference: str, *, locator_kind: str = "file") -> LocatorRecord:
        """Move an entity without touching its identity."""
        previous = self.get(entity_id, locator_kind)
        if previous is None:
            raise SemanticLocatorError(f"entity has no {locator_kind} locator to move")
        if new_reference == previous.reference:
            return previous
        return self.set_locator(
            entity_id=entity_id,
            locator_kind=locator_kind,
            reference=new_reference,
            line_start=previous.line_start,
            line_end=previous.line_end,
            symbol=previous.symbol,
        )


@dataclass(frozen=True, slots=True)
class RelationRecord:
    relation_id: str
    source_entity_id: str
    relation_kind: str
    target_entity_id: str | None
    external_target: str | None = None
    directed: bool = True
    declared_by: str | None = None
    observed_utc: str | None = None
    notes: str | None = None

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": RELATION_SCHEMA_VERSION,
            "relation_id": self.relation_id,
            "source_entity_id": self.source_entity_id,
            "relation_kind": self.relation_kind,
            "target_entity_id": self.target_entity_id,
            "directed": self.directed,
            "external_target": self.external_target,
            "declared_by": self.declared_by,
            "observed_utc": self.observed_utc,
            "notes": self.notes,
        }


def derive_relation_id(source_entity_id: str, relation_kind: str, target_entity_id: str | None,
                       *, external_target: str | None = None, directed: bool = True) -> str:
    basis = {
        "contract": RELATION_SCHEMA_VERSION,
        "source": str(source_entity_id),
        "kind": str(relation_kind),
        "target": str(target_entity_id) if target_entity_id else None,
    }
    # Retain existing directed internal edge IDs; distinguish facts that the
    # old derivation incorrectly collapsed into the same identity.
    if external_target is not None:
        basis["external_target"] = external_target
    if not directed:
        basis["directed"] = False
    return _digest_id(RELATION_ID_PREFIX, basis)


class RelationRegistry:
    """Typed graph edges with enforced endpoint integrity."""

    def __init__(self, entities: EntityRegistry) -> None:
        self._entities = entities
        self._relations: dict[str, RelationRecord] = {}

    def __len__(self) -> int:
        return len(self._relations)

    def add_relation(
        self,
        *,
        source_entity_id: str,
        relation_kind: str,
        target_entity_id: str | None = None,
        external_target: str | None = None,
        directed: bool = True,
        declared_by: str | None = None,
        observed_utc: str | None = None,
        notes: str | None = None,
    ) -> RelationRecord:
        if relation_kind not in RELATION_KINDS:
            raise SemanticLocatorError(f"relation kind is invalid: {relation_kind}")
        if relation_kind == "located_at":
            raise SemanticLocatorError("located_at relationships must be derived from current locators")
        if not isinstance(directed, bool):
            raise SemanticLocatorError("relation directed must be a boolean")
        if target_entity_id is not None and external_target is not None:
            raise SemanticLocatorError("a relation cannot assert both an entity and an external target")
        if external_target is not None and (
            not isinstance(external_target, str) or not external_target.strip()
            or len(external_target) > 1000
        ):
            raise SemanticLocatorError("external_target must be a bounded non-empty string")
        source_entity_id = str(source_entity_id)
        source = self._entities.get(source_entity_id)
        if source is None or source.lifecycle_state == "retired":
            raise SemanticLocatorError(
                f"relation source is not a live entity: {source_entity_id}"
            )
        if target_entity_id is None:
            if relation_kind in GRAPH_ONLY_RELATIONS:
                raise SemanticLocatorError(
                    f"relation kind {relation_kind} requires a target entity; "
                    "it may not dangle outside the graph"
                )
            if not str(external_target or "").strip():
                raise SemanticLocatorError(
                    "a relation without a target entity requires an external_target"
                )
        else:
            target = self._entities.get(str(target_entity_id))
            if target is None:
                raise SemanticLocatorError(
                    f"relation target is a dangling endpoint: {target_entity_id}"
                )
            if target.lifecycle_state == "retired":
                raise SemanticLocatorError(
                    f"relation target is retired: {target_entity_id}"
                )
            if target_entity_id == source_entity_id and relation_kind != "references":
                raise SemanticLocatorError(
                    f"self-referential {relation_kind} relation is not permitted"
                )
        record = RelationRecord(
            relation_id=derive_relation_id(
                source_entity_id, relation_kind, target_entity_id,
                external_target=external_target, directed=directed,
            ),
            source_entity_id=source_entity_id,
            relation_kind=relation_kind,
            target_entity_id=str(target_entity_id) if target_entity_id else None,
            external_target=external_target,
            directed=directed,
            declared_by=declared_by,
            observed_utc=observed_utc,
            notes=notes,
        )
        existing = self._relations.get(record.relation_id)
        if existing is not None:
            if existing != record:
                raise SemanticLocatorError("conflicting relation declaration; existing provenance is retained")
            return existing
        self._relations[record.relation_id] = record
        return record

    def get(self, relation_id: str) -> RelationRecord | None:
        return self._relations.get(str(relation_id))

    def all_relations(self) -> tuple[RelationRecord, ...]:
        return tuple(self._relations[key] for key in sorted(self._relations))

    def dangling_relations(self) -> tuple[RelationRecord, ...]:
        """Relations whose endpoints no longer resolve to live entities.

        Re-checked on demand rather than trusted at registration, because an
        endpoint can be retired after the edge was accepted.
        """
        broken: list[RelationRecord] = []
        for record in self.all_relations():
            for endpoint in (record.source_entity_id, record.target_entity_id):
                if endpoint is None:
                    continue
                entity = self._entities.get(endpoint)
                if entity is None or entity.lifecycle_state == "retired":
                    broken.append(record)
                    break
        return tuple(broken)

    def assert_no_dangling(self) -> None:
        broken = self.dangling_relations()
        if broken:
            ids = ", ".join(sorted(item.relation_id for item in broken))
            raise SemanticLocatorError(f"dangling relation endpoints: {ids}")

    def edges_from(self, entity_id: str) -> tuple[RelationRecord, ...]:
        return tuple(
            record
            for record in self.all_relations()
            if record.source_entity_id == str(entity_id)
        )

    def bind_locators(
        self, locators: LocatorRegistry
    ) -> tuple[RelationRecord, ...]:
        """Derive ``located_at`` edges from current locators.

        Derived, never asserted, so a location edge can never disagree with the
        locator record it claims to reflect.
        """
        produced: list[RelationRecord] = []
        for locator in locators.all_locators():
            if locator.locator_kind not in {"file", "directory", "line_range", "symbol", "uri"}:
                continue
            entity = self._entities.get(locator.entity_id)
            if entity is None or entity.lifecycle_state == "retired":
                raise SemanticLocatorError("derived location references a missing or retired entity")
            record = RelationRecord(
                relation_id=derive_relation_id(
                    locator.entity_id, "located_at", None, external_target=locator.reference
                ),
                source_entity_id=locator.entity_id,
                relation_kind="located_at",
                target_entity_id=None,
                external_target=locator.reference,
                directed=True,
                declared_by="semantic_locator.bind_locators",
            )
            produced.append(record)
        return tuple(produced)

    def relation_document(self) -> dict[str, Any]:
        return {
            "schema_version": "px.semantic-relation-registry/1.0",
            "relation_contract": RELATION_SCHEMA_VERSION,
            "relation_count": len(self._relations),
            "dangling_count": len(self.dangling_relations()),
            "relations": [record.as_mapping() for record in self.all_relations()],
        }
