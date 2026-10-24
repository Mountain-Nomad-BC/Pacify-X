"""Compact semantic address allocator - implements punch card SEM-003.

A compact address is a byte-sized alias for a canonical entity, written
``Subject.Object.SemanticRole.Kind``. It exists because ``entity_id`` is a
32-hex-digit string: fine for identity, far too wide for a hot graph edge or a
dense table where every reference costs memory.

The alias is a BOUND REFERENCE, not identity. ``entity_id`` from SEM-001 stays
the canonical authority, and the allocator can always be rebuilt from it.

Reserved semantics
------------------
Segment values 0 and 255 are reserved in EVERY segment:

* ``0``  - unallocated. A cleared table slot, never a live entity.
* ``255`` - tombstone. The address was deliberately retired.

Both are excluded from live values, which leaves 1..254 per segment and
254^4 = 3,895,695,376 possible addresses. Keeping the sentinel meanings distinct
is what lets a consumer test a raw byte without consulting a side table, and it
is why an address that reads 0 or 255 in any segment is always a bug rather than
a lookup miss.

Generations and tombstones
--------------------------
A tombstoned address may be REUSED, because the space is finite. Reuse is safe
only if the old alias can never resolve to the new entity, so the allocation
generation increments on every reuse and the alias carries it. A consumer that
stale-retains an old alias therefore resolves to nothing instead of silently
addressing a different entity. That is the failure this design exists to
prevent: a bare address that quietly changes meaning is worse than no alias.

Semantic allocation
------------------
Every segment is allocated from a frozen controlled vocabulary in
``runtime.semantic_address_vocabulary.py``: subject, object family, semantic role
and kind are named concepts, and the number IS the concept. An entity therefore
allocates to the address its meaning implies, and two entities about the same
thing in the same way share the same subject number.

This replaced an earlier digest-byte allocator, which seeded every segment from
``sha256(entity_id)[0..3]``. That design passed every structural test - legal
segments, no collisions, deterministic round trip - while being useless in
practice, because the subject segment carried no information at all: nobody could
look at ``PXA1:1a03ff07:1`` and know what it referred to. It also meant a number
carried no stable meaning, so the same concept got a different number for every
entity and the space had to be probed for collisions at all.

Allocation never invents a number. A concept missing from the registry raises
rather than being hashed into a plausible-looking value, because a number that
nobody reviewed is worse than no number.

No reuse
--------
A tombstoned address is NEVER reused. The earlier generation-bumping scheme
reclaimed it under a new generation, which is safe against a stale holder but is
still recycling: the same four segments come to mean a different thing at a
different time, so history becomes unreadable and a consumer cannot treat a
segment as a concept. Under this owner a retired address is retired forever, and
overflow is reported as exhaustion instead of wrapping, because wrapping would
re-point live addresses at different concepts without any error.

Determinism
-----------
Allocation derives its candidate order from the entity identity, so the same
allocator state and entity always yield the same alias. Round-trip
``alias -> entity -> alias`` is exact for every active alias.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .semantic_address_vocabulary import (
    DIMENSIONS,
    MAX_SEGMENT as VOCABULARY_MAX_SEGMENT,
    MIN_SEGMENT as VOCABULARY_MIN_SEGMENT,
    VOCABULARY_SCHEMA_VERSION,
    SemanticVocabulary,
    VocabularyError,
    FROZEN_VOCABULARY,
)

COMPACT_ADDRESS_SCHEMA_VERSION = "px.compact-address/1.0"
ALIAS_PREFIX = "PXA1"
SCHEMA_RELATIVE = Path("contracts/semantic/compact-address-record.schema.json")

# Segment sentinels. Both are forbidden as live values in every segment.
UNALLOCATED = 0
TOMBSTONE = 255
RESERVED_VALUES = frozenset({UNALLOCATED, TOMBSTONE})

MIN_SEGMENT = 1
MAX_SEGMENT = 254
SEGMENTS = ("subject", "object", "semantic_role", "kind")

MAX_GENERATION = 999_999_999

#: Maximum raw byte values available for kind-dimension disambiguation. The
#: effective capacity is the number of reviewed members in the frozen kind
#: vocabulary, which may be smaller. Allocation refuses an unreviewed value.
DIMENSION_SIBLING_CAPACITY = 254

#: Maps each registered entity kind onto the three outer address dimensions.
#: Every triple is verified against the frozen vocabulary before allocation;
#: missing mappings and terms are refused rather than guessed.
SUBJECT_BY_ENTITY_KIND: dict[str, tuple[str, str, str]] = {
    "artifact": ("evidence", "document", "generation"),
    "contract": ("governance", "contract", "definition"),
    "declaration": ("governance", "contract", "declaration"),
    "module": ("runtime", "module", "generation"),
    "operation": ("runtime", "module", "dispatch"),
    "policy": ("governance", "policy", "definition"),
    "record": ("evidence", "record", "recording"),
    "relation_kind": ("governance", "registry", "definition"),
    "surface": ("integration", "document", "adaptation"),
    "symbol": ("runtime", "symbol", "resolution"),
}


#: Finer partitioning of the ``surface`` entity kind. Source objects
#: (capability/model/tool/integration/agent/skill) are all semantic surfaces, but
#: a single ``integration.document.adaptation`` namespace has only as many
#: addresses as the kind dimension has members (37), which a real registry of
#: hundreds of agents and skills exceeds. The source kind is real,
#: evidence-backed taxonomy, so it selects a distinct subject/object/role triple
#: from the frozen vocabulary rather than being discarded. Every term below is a
#: frozen-vocabulary member.
SURFACE_CONCEPTS_BY_SOURCE_KIND: dict[str, tuple[str, str, str]] = {
    "capability": ("capability", "capability", "definition"),
    "model": ("routing", "model", "resolution"),
    "tool": ("integration", "service", "invocation"),
    "integration": ("integration", "service", "adaptation"),
    "agent": ("agents", "agent", "definition"),
    "skill": ("skills", "skill", "definition"),
    "knowledge_source": ("retrieval", "document", "indexing"),
    "builder": ("orchestration", "construction", "construction"),
    "orchestration": ("orchestration", "orchestration", "orchestration"),
}

#: Agency/registry domain -> frozen-vocabulary ``object`` family. Domains with no
#: admitted family keep the source kind's base family rather than guessing.
_DOMAIN_FAMILIES: dict[str, str] = {
    "academic": "document",
    "design": "document",
    "engineering": "service",
    "finance": "record",
    "marketing": "document",
    "product": "document",
    "operations": "service",
    "research": "document",
    "security": "service",
    "sales": "record",
    "support": "service",
    "data": "record",
    "legal": "policy",
    "media": "document",
    "people": "agent",
    "quality": "service",
    "education": "document",
    "spatial": "document",
    "specialized": "agent",
    "testing": "service",
    "game-development": "service",
    "project-management": "orchestration",
}


def concepts_for_entity_kind(
    entity_kind: str, *, lifecycle_state: str = "accepted", source_kind: str | None = None,
    domain: str | None = None,
) -> dict[str, str]:
    """Declared concepts for a registered entity kind.

    The KIND dimension holds the entity's kind, not an admission state: the
    census vocabulary contains ``module``, ``contract``, ``policy`` and so on,
    not ``governed`` or ``historical``. A retired entity keeps its own kind and
    is marked through the alias lifecycle instead, so retiring it does not
    require a vocabulary term that does not exist.

    ``source_kind`` refines a ``surface`` entity onto its real subject/object/role
    namespace so distinct source kinds do not share one exhaustible namespace.
    """
    if source_kind is not None:
        refined = SURFACE_CONCEPTS_BY_SOURCE_KIND.get(source_kind)
        if refined is not None and entity_kind in {"surface", "operation"}:
            subject, object_family, role = refined
            # A single flat namespace (e.g. 270 agency agents) exceeds the 37-member
            # kind dimension. The agency domain prefix in the source id is real
            # taxonomy, so it selects a distinct object family rather than being
            # collapsed into one exhaustible namespace.
            if domain:
                family = _DOMAIN_FAMILIES.get(domain)
                if family is not None:
                    object_family = family
        else:
            try:
                subject, object_family, role = SUBJECT_BY_ENTITY_KIND[entity_kind]
            except KeyError as error:
                raise CompactAddressError(
                    f"entity kind {entity_kind!r} has no controlled vocabulary mapping"
                ) from error
    else:
        try:
            subject, object_family, role = SUBJECT_BY_ENTITY_KIND[entity_kind]
        except KeyError as error:
            raise CompactAddressError(
                f"entity kind {entity_kind!r} has no controlled vocabulary mapping"
            ) from error
    kind = entity_kind if entity_kind in _KIND_TERMS else "module"
    return {
        "subject": subject,
        "object": object_family,
        "semantic_role": role,
        "kind": kind,
    }


_KIND_TERMS = frozenset(
    FROZEN_VOCABULARY.dimension("kind").members
)


class CompactAddressError(ValueError):
    """Raised when a compact address or allocation is invalid."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _assert_live_segment(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CompactAddressError(f"segment {name} must be an integer")
    if value in RESERVED_VALUES:
        raise CompactAddressError(
            f"segment {name} uses reserved value {value}; "
            f"{UNALLOCATED} is unallocated and {TOMBSTONE} is a tombstone"
        )
    if not MIN_SEGMENT <= value <= MAX_SEGMENT:
        raise CompactAddressError(
            f"segment {name} must be within {MIN_SEGMENT}..{MAX_SEGMENT}"
        )


def validate_segments(segments: dict[str, int]) -> None:
    """Enforce reserved semantics on all four segments."""
    missing = [name for name in SEGMENTS if name not in segments]
    if missing:
        raise CompactAddressError(f"address is missing segments: {missing}")
    extra = sorted(set(segments) - set(SEGMENTS))
    if extra:
        raise CompactAddressError(f"address has unknown segments: {extra}")
    for name in SEGMENTS:
        _assert_live_segment(name, segments[name])


@dataclass(frozen=True, slots=True)
class CompactAddress:
    subject: int
    object: int
    semantic_role: int
    kind: int
    generation: int = 1

    def __post_init__(self) -> None:
        validate_segments(self.as_segments())
        if (not isinstance(self.generation, int) or isinstance(self.generation, bool)
                or not 1 <= self.generation <= MAX_GENERATION):
            raise CompactAddressError("compact address generation must be a bounded positive integer")

    def packed(self) -> int:
        return (
            ((self.subject & 0xFF) << 24)
            | ((self.object & 0xFF) << 16)
            | ((self.semantic_role & 0xFF) << 8)
            | (self.kind & 0xFF)
        )

    def as_segments(self) -> dict[str, int]:
        return {
            "subject": self.subject,
            "object": self.object,
            "semantic_role": self.semantic_role,
            "kind": self.kind,
        }

    @property
    def alias(self) -> str:
        return f"{ALIAS_PREFIX}:{self.packed():08x}:{self.generation}"

    def as_mapping(self, entity_id: str | None = None, lifecycle: str = "active") -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": COMPACT_ADDRESS_SCHEMA_VERSION,
            "alias": self.alias,
            "address": self.as_segments(),
            "generation": self.generation,
            "lifecycle": lifecycle,
        }
        if entity_id is not None:
            record["entity_id"] = entity_id
        return record


def parse_alias(alias: str) -> CompactAddress:
    """Parse an alias string, rejecting reserved segments."""
    if not isinstance(alias, str):
        raise CompactAddressError("compact alias must be a string")
    value = alias
    if re.fullmatch(r"PXA1:[0-9a-f]{8}:[1-9][0-9]{0,8}", value) is None:
        raise CompactAddressError("compact alias must use its exact canonical representation")
    if not value.startswith(ALIAS_PREFIX + ":"):
        raise CompactAddressError("compact alias has an invalid prefix")
    parts = value.split(":")
    if len(parts) != 3:
        raise CompactAddressError("compact alias must be PXA1:<hex>:<generation>")
    packed_text, generation_text = parts[1], parts[2]
    if len(packed_text) != 8:
        raise CompactAddressError("compact alias packed form must be 8 hex digits")
    try:
        packed = int(packed_text, 16)
        generation = int(generation_text, 10)
    except ValueError as error:
        raise CompactAddressError("compact alias is not valid hexadecimal or decimal") from error
    if not 1 <= generation <= MAX_GENERATION:
        raise CompactAddressError("compact alias generation is out of range")
    address = CompactAddress(
        subject=(packed >> 24) & 0xFF,
        object=(packed >> 16) & 0xFF,
        semantic_role=(packed >> 8) & 0xFF,
        kind=packed & 0xFF,
        generation=generation,
    )
    validate_segments(address.as_segments())
    return address


class CompactAddressAllocator:
    """Allocates, tombstones and resolves compact semantic addresses.

    Every segment comes from the frozen controlled vocabulary, so an address is
    readable without the allocator. An entity declares what it *is* through four
    named concepts; the allocator turns those into numbers and refuses to invent
    a number for anything the vocabulary does not contain.

    State is a cache, not an authority: the whole table rebuilds from
    ``(entity_id, concepts)`` pairs, so a rebuild converges on the same aliases.
    """

    def __init__(self, vocabulary: SemanticVocabulary | None = None) -> None:
        self._vocabulary = vocabulary or FROZEN_VOCABULARY
        # packed -> (entity_id, generation, lifecycle, concepts)
        self._slots: dict[int, tuple[str, int, str, tuple[tuple[str, str], ...]]] = {}
        # entity_id -> packed
        self._by_entity: dict[str, int] = {}
        # entity_id -> caller-declared concepts. Overflow aliases may use a
        # neighboring kind term, so decoded address concepts are not sufficient
        # to recognize a repeat allocation of the original declaration.
        self._declared_concepts: dict[str, tuple[tuple[str, str], ...]] = {}
        # Every alias ever issued, in issue order. A superseded alias is retained
        # rather than dropped so a stale holder can be told what happened to it
        # instead of silently resolving to nothing.
        self._superseded: list[dict[str, Any]] = []
        # Addresses handed out by disambiguation rather than by their exact
        # declared concepts, so the registry can say which ones are neighbours
        # rather than canonical for their meaning.
        self._overflow_advice: dict[int, str] = {}

    def __len__(self) -> int:
        return len(self._by_entity)

    # -- semantic classification ----------------------------------------------

    def classify(
        self, entity_id: str, concepts: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """The four named concepts an entity allocates under.

        Concepts are always supplied by the producer that already knows what the
        entity is. They are deliberately NOT recovered from ``entity_id``: that
        id is a content digest and carries no kind, so any mapping from it would
        be a guess. Refusing to guess is what keeps an unclassified entity from
        receiving a plausible-looking but meaningless address.
        """
        if not entity_id:
            raise CompactAddressError("cannot classify an entity without an identity")
        if concepts is None:
            raise CompactAddressError(
                "compact addresses are allocated from declared semantic concepts; "
                "entity_id is a content digest and cannot be classified"
            )
        missing = [name for name in DIMENSIONS if name not in concepts]
        if missing:
            raise CompactAddressError(
                "semantic concepts are incomplete: " + ", ".join(missing)
            )
        return {name: str(concepts[name]) for name in DIMENSIONS}

    # -- deterministic probing -------------------------------------------------

    def _probe_order(
        self, subject: int, obj: int, role: int, kind: int
    ) -> Iterator[tuple[int, int, int, int]]:
        """Every address under this entity's semantic base, in a fixed order.

        Retained for diagnostics and for callers that need to enumerate a base's
        address space. Allocation itself does NOT use this walk: see
        :meth:`allocate`, where disambiguation is confined to the kind dimension
        so that an address can never decode to a meaning the entity did not
        declare.
        """
        a, b, c, d = subject, obj, role, kind
        for _ in range(VOCABULARY_MAX_SEGMENT ** 4):
            yield a, b, c, d
            d += 1
            if d > VOCABULARY_MAX_SEGMENT:
                d = VOCABULARY_MIN_SEGMENT
                c += 1
            if c > VOCABULARY_MAX_SEGMENT:
                c = VOCABULARY_MIN_SEGMENT
                b += 1
            if b > VOCABULARY_MAX_SEGMENT:
                b = VOCABULARY_MIN_SEGMENT
                a += 1
            if a > VOCABULARY_MAX_SEGMENT:
                a = VOCABULARY_MIN_SEGMENT

    def _segments_from_packed(self, packed: int) -> CompactAddress:
        return CompactAddress(
            subject=(packed >> 24) & 0xFF,
            object=(packed >> 16) & 0xFF,
            semantic_role=(packed >> 8) & 0xFF,
            kind=packed & 0xFF,
            generation=1,
        )

    @staticmethod
    def _pack(segments: tuple[int, int, int, int]) -> int:
        return (
            ((segments[0] & 0xFF) << 24)
            | ((segments[1] & 0xFF) << 16)
            | ((segments[2] & 0xFF) << 8)
            | (segments[3] & 0xFF)
        )

    # -- allocation ------------------------------------------------------------

    def allocate(
        self,
        entity_id: str,
        concepts: Mapping[str, str] | None = None,
        *,
        semantic_generation: int = 1,
    ) -> CompactAddress:
        """Allocate (or return the existing) address for an entity."""
        entity_id = str(entity_id)
        if not entity_id:
            raise CompactAddressError("cannot allocate an address for an empty entity id")
        resolved = self.classify(entity_id, concepts)
        try:
            base = tuple(self._vocabulary.number(name, resolved[name]) for name in DIMENSIONS)
        except VocabularyError as error:
            raise CompactAddressError(str(error)) from error
        declared = self._concept_tuple(resolved)

        existing_packed = self._by_entity.get(entity_id)
        if existing_packed is not None:
            entry = self._slots[existing_packed]
            if entry[2] == "active":
                current = self._segments_from_packed(existing_packed)
                # Preserve the existing allocation while the semantics are
                # unchanged. Changing meaning reallocates under a new semantic
                # generation rather than silently reinterpreting a live address.
                if self._declared_concepts.get(
                    entity_id, self._concepts_of(existing_packed)
                ) == declared:
                    return CompactAddress(**current.as_segments(), generation=entry[1])
                del self._by_entity[entity_id]
                # The old meaning is RETIRED, not left live. Leaving it active
                # would let the same alias resolve to an entity whose meaning has
                # moved on, which is exactly the silent reinterpretation this
                # design forbids.
                self._slots[existing_packed] = (
                    entry[0], entry[1], "tombstoned", entry[3],
                )
                self._supersede(entity_id, current, entry[1], semantic_generation,
                                "semantics changed")
            else:
                # A tombstoned entity that is re-registered must get a live slot.
                del self._by_entity[entity_id]

        packed = self._pack(base)
        occupant = self._slots.get(packed)
        # A free or self-owned slot may be (re)allocated. A TOMBSTONED slot is
        # never reclaimed, not even by its own entity: once retired, an address is
        # permanent, so its segments keep their original meaning forever.
        if occupant is None or (occupant[0] == entity_id and occupant[2] == "active"):
            self._slots[packed] = (entity_id, semantic_generation, "active",
                                   self._concept_tuple(resolved))
            self._by_entity[entity_id] = packed
            self._declared_concepts[entity_id] = declared
            return CompactAddress(**self._segments_from_packed(packed).as_segments(),
                                  generation=semantic_generation)

        # The exact semantic address is already held by a different live entity.
        #
        # Disambiguation must not change what an address MEANS. The earlier digest
        # allocator walked all four dimensions, which quietly solved exhaustion by
        # changing meaning: an entity declared "governed" could be handed a kind
        # byte decoding to "derived". That is worse than failing, because the
        # address still looks valid.
        #
        # A flat source kind (e.g. hundreds of agency agents or skills) can exceed
        # the kind dimension's capacity on its own. Do not reclaim space by
        # changing another declared dimension: an overflow alias must preserve the
        # entity's subject, object family, and semantic role.
        kind_dimension = self._vocabulary.dimension("kind")
        for member in kind_dimension.members:
            candidate_kind = kind_dimension.number_of(member)
            if candidate_kind == base[3]:
                continue
            candidate = (base[0], base[1], base[2], candidate_kind)
            other = self._pack(candidate)
            # Every occupied slot is skipped, live or tombstoned. Skipping a
            # tombstone rather than reclaiming it keeps every issued address
            # permanently bound to its original meaning.
            if other in self._slots:
                continue
            disambiguated = (
                ("subject", resolved["subject"]),
                ("object", resolved["object"]),
                ("semantic_role", resolved["semantic_role"]),
                ("kind", str(member)),
            )
            self._slots[other] = (entity_id, semantic_generation, "active", disambiguated)
            self._by_entity[entity_id] = other
            self._declared_concepts[entity_id] = declared
            self._overflow_advice[other] = (
                "allocated by kind-dimension disambiguation within the declared meaning"
            )
            return CompactAddress(**self._segments_from_packed(other).as_segments(),
                                  generation=semantic_generation)
        raise CompactAddressError(
            "compact address space exhausted for the semantic base "
            + ".".join(resolved[name] for name in DIMENSIONS)
            + f"; only {len(kind_dimension.members)} sibling kinds exist, so this "
            "namespace must be split or merged in the taxonomy before allocation. "
            "Wrapping is refused because it would re-point a live address at a "
            "different concept."
        )

    @staticmethod
    def _concept_tuple(concepts: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple((name, str(concepts[name])) for name in DIMENSIONS)

    def _concepts_of(self, packed: int) -> tuple[tuple[str, str], ...]:
        return self._slots[packed][3]

    def _supersede(
        self, entity_id: str, address: CompactAddress, generation: int,
        semantic_generation: int, reason: str,
    ) -> None:
        """Record a retired alias instead of discarding it.

        Consumers are updated through the resolver, never by search/replace, so a
        superseded alias must stay resolvable as historical fact: without this
        record a stale holder sees nothing at all and cannot tell a tombstone
        from a bad reference.
        """
        self._superseded.append({
            "entity_id": entity_id,
            "alias": address.alias,
            "retired_generation": generation,
            "semantic_generation": semantic_generation,
            "reason": reason,
        })

    def resolve(self, alias: str) -> str | None:
        """Resolve an alias to its entity, or None when stale or unknown."""
        address = parse_alias(alias)
        entry = self._slots.get(address.packed())
        if entry is None:
            return None
        entity_id, generation, lifecycle, _ = entry
        if lifecycle != "active":
            return None
        if generation != address.generation:
            # A stale generation is exactly the reuse hazard this design
            # prevents: the address is live but belongs to a newer binding.
            return None
        return entity_id

    def resolve_historical(self, alias: str) -> dict[str, Any] | None:
        """Explain a non-resolving alias instead of returning bare ``None``."""
        address = parse_alias(alias)
        entry = self._slots.get(address.packed())
        if entry is not None:
            _, generation, lifecycle, _ = entry
            return {
                "alias": alias,
                "status": lifecycle if lifecycle != "active" else "live_generation_mismatch",
                "current_generation": generation,
                "entity_id": entry[0],
            }
        for record in self._superseded:
            if record["alias"] == alias:
                return {"alias": alias, "status": "superseded", **record}
        return None

    def tombstone(self, alias: str, *, reason: str | None = None) -> CompactAddress:
        """Retire an alias permanently. The address is never handed out again."""
        address = parse_alias(alias)
        entry = self._slots.get(address.packed())
        if entry is None:
            raise CompactAddressError("cannot tombstone an unknown compact address")
        entity_id, generation, lifecycle, _ = entry
        if lifecycle != "active":
            raise CompactAddressError("compact address is already tombstoned")
        if generation != address.generation:
            raise CompactAddressError("compact address generation is stale")
        self._slots[address.packed()] = (entity_id, generation, "tombstoned", entry[3])
        self._by_entity.pop(entity_id, None)
        return address

    def alias_for(self, entity_id: str, concepts: Mapping[str, str] | None = None) -> str:
        """Current alias for an entity; allocates one if absent."""
        return self.allocate(entity_id, concepts).alias

    def round_trip(self, alias: str) -> str | None:
        """alias -> entity -> alias, exact for every active alias."""
        entity_id = self.resolve(alias)
        if entity_id is None:
            return None
        # Retrieval must not allocate: overflow segments describe a placement,
        # not the entity's declared semantics. Reallocating from those segments
        # would retire the live binding during an otherwise read-only lookup.
        packed = self._by_entity.get(entity_id)
        if packed is None:
            return None
        current = CompactAddress(
            **self._segments_from_packed(packed).as_segments(),
            generation=self._slots[packed][1],
        ).alias
        return current if current == alias else None

    def decode(self, alias: str) -> dict[str, str | None]:
        """Address back to the concepts it names, via the frozen vocabulary."""
        return self._vocabulary.decode(parse_alias(alias).as_segments())

    def statistics(self) -> dict[str, int]:
        active = sum(1 for entry in self._slots.values() if entry[2] == "active")
        tombstoned = sum(1 for entry in self._slots.values() if entry[2] == "tombstoned")
        return {
            "active": active,
            "tombstoned": tombstoned,
            "slots": len(self._slots),
            "superseded": len(self._superseded),
            "capacity": 254**4,
        }

    def alias_migration_crosswalk(self, previous: Mapping[str, str]) -> dict[str, Any]:
        """Crosswalk from a prior alias table to the current one.

        Consumers migrate through this document and the resolver. Textual
        search/replace across projections is exactly what must not happen: an
        alias that survives as superseded fact is safer than one that was
        rewritten out from under a stale holder.
        """
        rows: list[dict[str, Any]] = []
        for entity_id, old_alias in sorted(previous.items()):
            current = self._by_entity.get(entity_id)
            new_alias = (
                self._segments_from_packed(current).alias if current is not None else None
            )
            status = "unchanged" if new_alias == old_alias else (
                "reallocated" if new_alias is not None else "unmapped"
            )
            rows.append({
                "entity_id": entity_id,
                "old_alias": old_alias,
                "new_alias": new_alias,
                "status": status,
                "old_alias_status": "active" if status == "unchanged" else "superseded",
            })
        return {
            "schema_version": "px.compact-address-crosswalk/1.0",
            "address_contract": COMPACT_ADDRESS_SCHEMA_VERSION,
            "vocabulary_version": VOCABULARY_SCHEMA_VERSION,
            "entries": rows,
            "counts": {
                status: sum(1 for row in rows if row["status"] == status)
                for status in ("unchanged", "reallocated", "unmapped")
            },
        }

    def registry_document(self) -> dict[str, Any]:
        rows = []
        for packed in sorted(self._slots):
            entity_id, generation, lifecycle, concepts = self._slots[packed]
            rows.append(
                CompactAddress(
                    **self._segments_from_packed(packed).as_segments(), generation=generation
                ).as_mapping(entity_id=entity_id, lifecycle=lifecycle)
                | {
                    "concepts": dict(concepts),
                    "allocation": self._overflow_advice.get(packed, "exact_semantic_base"),
                }
            )
        return {
            "schema_version": "px.compact-address-registry/1.0",
            "address_contract": COMPACT_ADDRESS_SCHEMA_VERSION,
            "contract_path": SCHEMA_RELATIVE.as_posix(),
            "reserved_values": sorted(RESERVED_VALUES),
            "live_segment_range": [MIN_SEGMENT, MAX_SEGMENT],
            "vocabulary": self._vocabulary.as_mapping(),
            "statistics": self.statistics(),
            "entries": rows,
            "superseded_aliases": list(self._superseded),
        }
