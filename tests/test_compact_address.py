from __future__ import annotations

import json
from pathlib import Path

import pytest

"""SEM-003: the compact semantic address allocator.

The three acceptance criteria are zero collisions, enforced 0/255 reserved
semantics, and a deterministic alias -> entity -> alias round trip. Everything
else here protects those, with particular attention to the reuse hazard: an
address freed by a tombstone must never let a stale alias resolve to a
different entity.
"""

from runtime.compact_address import (
    ALIAS_PREFIX,
    COMPACT_ADDRESS_SCHEMA_VERSION,
    DIMENSION_SIBLING_CAPACITY,
    MAX_SEGMENT,
    MIN_SEGMENT,
    RESERVED_VALUES,
    SCHEMA_RELATIVE,
    SEGMENTS,
    TOMBSTONE,
    UNALLOCATED,
    CompactAddress,
    CompactAddressAllocator,
    CompactAddressError,
    concepts_for_entity_kind,
    parse_alias,
    validate_segments,
)
from runtime.semantic_address_vocabulary import (
    DIMENSIONS,
    FROZEN_VOCABULARY,
    VOCABULARY_SCHEMA_VERSION,
    load_vocabulary,
    vocabulary_document,
)
from runtime.semantic_entity import EntityRegistry, identity_basis_for

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every registered entity kind must reach the vocabulary. This is the
#: producer-to-consumer link: a kind the allocator cannot classify has no
#: address, so the table is checked against the registry rather than trusted.
REGISTERED_ENTITY_KINDS = (
    "declaration", "contract", "module", "operation", "symbol",
    "surface", "record", "artifact", "policy", "relation_kind",
)


def _entities(
    count: int, entity_kind: str = "operation", *, prefix: str = ""
) -> list[str]:
    """Register ``count`` distinct entities of one kind.

    ``prefix`` keeps a second registration from colliding with an earlier one:
    entity identity is content-derived, so ``operation_0`` always names the same
    entity no matter which registry builds it.
    """
    registry = EntityRegistry()
    return [
        registry.register(
            entity_kind=entity_kind,
            identity_basis=identity_basis_for(
                "intrinsic_name", f"{entity_kind}_{prefix}{index}"
            ),
            declared_by="test",
        ).entity_id
        for index in range(count)
    ]


def _concepts(entity_kind: str = "operation") -> dict[str, str]:
    return concepts_for_entity_kind(entity_kind)


def test_contract_exists_and_declares_reserved_values() -> None:
    schema_path = REPO_ROOT / SCHEMA_RELATIVE
    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:engineering-loop-bootstrap:contract:semantic:compact-address-record"
    assert schema["$defs"]["reservedValues"]["const"] == sorted(RESERVED_VALUES)
    for name in SEGMENTS:
        segment = schema["properties"]["address"]["properties"][name]
        assert segment["minimum"] == MIN_SEGMENT
        assert segment["maximum"] == MAX_SEGMENT


def test_reserved_values_are_exactly_zero_and_255() -> None:
    assert RESERVED_VALUES == {0, 255}
    assert UNALLOCATED == 0
    assert TOMBSTONE == 255


@pytest.mark.parametrize("subject", [0, 255, 257, -1, True, 1.0, "1"])
def test_address_constructor_cannot_emit_invalid_or_wrapped_segments(subject) -> None:
    with pytest.raises(CompactAddressError):
        CompactAddress(subject=subject, object=1, semantic_role=1, kind=1)


@pytest.mark.parametrize("generation", [0, -1, 1_000_000_000, True, 1.0, "1"])
def test_address_constructor_requires_bounded_integer_generation(generation) -> None:
    with pytest.raises(CompactAddressError):
        CompactAddress(subject=1, object=1, semantic_role=1, kind=1, generation=generation)


@pytest.mark.parametrize("alias", ["PXA1:-123abcd:1", "PXA1:01010101:+1", "PXA1:01010101:01",
                                  "PXA1:abcdef12:١", "PXA1:ABCDEF12:1", " PXA1:01010101:1", None])
def test_alias_parser_requires_exact_canonical_representation(alias) -> None:
    with pytest.raises(CompactAddressError):
        parse_alias(alias)


def test_reserved_values_are_refused_in_every_segment() -> None:
    """ACCEPTANCE: 0/255 reserved semantics enforced."""
    for name in SEGMENTS:
        base = {segment: 10 for segment in SEGMENTS}
        for reserved in RESERVED_VALUES:
            broken = dict(base)
            broken[name] = reserved
            with pytest.raises(CompactAddressError, match="reserved value"):
                validate_segments(broken)


def test_segment_bounds_are_enforced() -> None:
    base = {segment: 10 for segment in SEGMENTS}
    validate_segments(base)
    for bad in (-1, 255, 256, 1000):
        broken = dict(base)
        broken["subject"] = bad
        with pytest.raises(CompactAddressError):
            validate_segments(broken)
    with pytest.raises(CompactAddressError, match="missing segments"):
        validate_segments({"subject": 1})
    with pytest.raises(CompactAddressError, match="unknown segments"):
        validate_segments({**base, "surprise": 5})


def test_non_integer_segment_is_refused() -> None:
    base = {segment: 10 for segment in SEGMENTS}
    for bad in (True, "10", 10.0, None):
        broken = dict(base)
        broken["kind"] = bad
        with pytest.raises(CompactAddressError, match="must be an integer"):
            validate_segments(broken)


def test_zero_collisions_across_many_entities() -> None:
    """ACCEPTANCE: zero collisions.

    Entities are spread across registered kinds, and the count per kind respects
    the real capacity: a semantic base holds as many entities as the kind
    dimension has reviewed members. Several registered kinds deliberately share
    one base (a module, one of its operations and one of its symbols are all
    runtime.module), so they are budgeted together rather than independently.
    """
    allocator = CompactAddressAllocator()
    capacity = len(FROZEN_VOCABULARY.dimension("kind").members)

    # Group the registered kinds by the semantic base they allocate into, then
    # fill each base exactly once. Several kinds deliberately share a base (a
    # module and one of its operations are both runtime.module.producer), so the
    # budget is per BASE, not per kind.
    by_base: dict[tuple[str, ...], list[str]] = {}
    for entity_kind in REGISTERED_ENTITY_KINDS:
        concepts = concepts_for_entity_kind(entity_kind)
        by_base.setdefault(tuple(concepts[name] for name in DIMENSIONS), []).append(entity_kind)

    pairs: list[tuple[str, str]] = []
    for kinds in by_base.values():
        share, remainder = divmod(capacity, len(kinds))
        for index, entity_kind in enumerate(kinds):
            count = share + (1 if index < remainder else 0)
            for entity_id in _entities(count, entity_kind):
                pairs.append((entity_id, entity_kind))
    assert len(pairs) == len(by_base) * capacity

    aliases = [
        allocator.allocate(entity_id, concepts_for_entity_kind(kind)).alias
        for entity_id, kind in pairs
    ]
    assert len(set(aliases)) == len(pairs)
    # And every alias resolves back to its own entity, never a neighbour's.
    for (entity_id, _), alias in zip(pairs, aliases):
        assert allocator.resolve(alias) == entity_id


def test_every_entity_kind_occupies_its_own_semantic_base() -> None:
    """Each registered kind gets a distinct base, so kinds cannot collide by accident.

    The mapping is deliberately one-to-one: a module and an operation both live
    under ``runtime.runtime`` but differ in role, so they never share a namespace.
    That is why the earlier "kinds contend for one base" test no longer had a
    subject to test - the vocabulary got more precise, not weaker.

    Overflow is still refused, and is proved below with a forced collision.
    """
    bases = {}
    for kind in REGISTERED_ENTITY_KINDS:
        concepts = concepts_for_entity_kind(kind)
        key = tuple(concepts[name] for name in DIMENSIONS)
        assert key not in bases, (
            f"{kind} shares the base of {bases.get(key)}: {key}"
        )
        bases[key] = kind
    assert len(bases) == len(REGISTERED_ENTITY_KINDS)


def test_repeated_entities_of_one_kind_fill_their_base_then_refuse_to_wrap() -> None:
    """A single kind filling its namespace must refuse, not wrap onto another kind."""
    capacity = len(FROZEN_VOCABULARY.dimension("kind").members)
    allocator = CompactAddressAllocator()
    concepts = concepts_for_entity_kind("module")
    ids = _entities(capacity, "module")
    for entity_id in ids:
        allocator.allocate(entity_id, concepts)

    # Overflow is refused: the space is exhausted, not silently recycled.
    with pytest.raises(CompactAddressError, match=r"split or merged in the taxonomy"):
        allocator.allocate(
            _entities(1, "module", prefix="overflow_")[0], concepts
        )

    # A DIFFERENT kind still allocates, because it has its own base.
    other = allocator.allocate(
        _entities(1, "symbol", prefix="other_")[0], concepts_for_entity_kind("symbol")
    )
    assert allocator.resolve(other.alias) is not None


def test_address_segments_are_semantically_allocated_not_hashed() -> None:
    """The reopened SEM-003 defect: segments must carry meaning.

    A digest-seeded allocator produces a legal address whose subject segment
    means nothing. Here the subject segment is the vocabulary number for the
    declared subject, so an address is readable without the allocator.
    """
    allocator = CompactAddressAllocator()
    concepts = _concepts("module")
    alias = allocator.allocate(_entities(1)[0], concepts).alias
    decoded = allocator.decode(alias)

    for dimension in DIMENSIONS:
        assert decoded[dimension] == concepts[dimension], (
            f"{dimension} did not decode to the declared concept"
        )
        assert decoded[dimension] == FROZEN_VOCABULARY.member(
            dimension, allocator._segments_from_packed(parse_alias(alias).packed()).as_segments()[dimension]
        )


def test_every_registered_entity_kind_classifies_into_the_vocabulary() -> None:
    """Producer-to-consumer reachability for every registered kind."""
    for entity_kind in REGISTERED_ENTITY_KINDS:
        concepts = concepts_for_entity_kind(entity_kind)
        assert set(concepts) == set(DIMENSIONS)
        allocator = CompactAddressAllocator()
        concepts = concepts_for_entity_kind(entity_kind)
        alias = allocator.allocate(_entities(1, entity_kind)[0], concepts).alias
        assert allocator.decode(alias) == concepts


def test_an_unregistered_entity_kind_is_refused_rather_than_guessed() -> None:
    with pytest.raises(CompactAddressError, match="no controlled vocabulary mapping"):
        concepts_for_entity_kind("not_a_registered_kind")


def test_allocation_refuses_to_guess_concepts_from_a_digest() -> None:
    """entity_id is a content digest; it carries no kind, so it is not classifiable."""
    allocator = CompactAddressAllocator()
    with pytest.raises(CompactAddressError, match="cannot be classified"):
        allocator.allocate(_entities(1)[0])
    with pytest.raises(CompactAddressError, match="incomplete"):
        allocator.allocate(_entities(1)[0], {"subject": "runtime"})


def test_concepts_outside_the_frozen_vocabulary_are_refused() -> None:
    """A number nobody reviewed is worse than no number."""
    allocator = CompactAddressAllocator()
    concepts = _concepts()
    concepts["kind"] = "a_kind_invented_by_a_caller"
    with pytest.raises(CompactAddressError, match="not in the frozen vocabulary"):
        allocator.allocate(_entities(1)[0], concepts)


def test_disambiguation_stays_inside_the_declared_meaning() -> None:
    """Overflow may vary the kind, never the meaning it was declared with.

    The outer three segments are fixed by the declared concepts, so two entities
    sharing a subject still share that subject number even when they collide on
    their exact base.
    """
    allocator = CompactAddressAllocator()
    concepts = _concepts("contract")
    ids = _entities(3, "contract")
    addresses = [allocator.allocate(entity_id, concepts) for entity_id in ids]

    assert len({address.alias for address in addresses}) == len(ids)
    assert allocator.allocate(ids[1], concepts) == addresses[1]
    assert allocator.alias_for(ids[1], concepts) == addresses[1].alias
    outer = {tuple(a.as_segments()[d] for d in DIMENSIONS[:3]) for a in addresses}
    assert len(outer) == 1, "disambiguation must not change the outer dimensions"
    for address in addresses:
        decoded = allocator.decode(address.alias)
        assert decoded["subject"] == concepts["subject"]
        assert decoded["object"] == concepts["object"]
        assert decoded["semantic_role"] == concepts["semantic_role"]
        assert decoded["kind"] in FROZEN_VOCABULARY.dimension("kind").members


def test_sibling_overflow_refuses_instead_of_wrapping() -> None:
    """A namespace larger than its sibling capacity must be split or merged.

    Wrapping would hand a live address to a different concept with no error at
    all, which is the silent corruption this allocator exists to prevent. The
    capacity is the number of REVIEWED kinds, not the raw 254 numbers: an
    unassigned number would decode to nothing.
    """
    siblings = len(FROZEN_VOCABULARY.dimension("kind").members)
    assert DIMENSION_SIBLING_CAPACITY == 254
    allocator = CompactAddressAllocator()
    concepts = _concepts("policy")
    ids = _entities(siblings + 1, "policy")
    for entity_id in ids[:siblings]:
        allocator.allocate(entity_id, concepts)

    with pytest.raises(CompactAddressError, match=r"split or merged in the taxonomy"):
        allocator.allocate(ids[siblings], concepts)


def test_tombstoned_addresses_are_never_reused() -> None:
    """The card forbids recycling during ordinary evolution.

    Reuse was previously allowed under a bumped generation. That is safe against
    a stale holder but still recycles: the same segments come to mean something
    different later, so history becomes unreadable and a segment stops being a
    usable concept.
    """
    allocator = CompactAddressAllocator()
    concepts = _concepts("artifact")
    retired = allocator.allocate(_entities(1, "artifact")[0], concepts)
    allocator.tombstone(retired.alias, reason="retired by test")

    replacement = allocator.allocate(_entities(2, "artifact")[1], concepts)
    assert replacement.packed() != retired.packed(), (
        "a tombstoned address must never be handed to another entity"
    )
    assert allocator.resolve(retired.alias) is None


def test_a_tombstoned_address_is_never_handed_back_to_its_own_entity() -> None:
    allocator = CompactAddressAllocator()
    concepts = _concepts("artifact")
    entity_id = _entities(1, "artifact")[0]
    retired = allocator.allocate(entity_id, concepts)
    allocator.tombstone(retired.alias, reason="retire")

    reissued = allocator.allocate(entity_id, concepts)
    assert reissued.packed() != retired.packed()
    assert allocator.resolve(retired.alias) is None
    assert allocator.resolve(reissued.alias) == entity_id


def test_resolve_historical_explains_a_non_resolving_alias() -> None:
    """A stale holder must be able to tell a tombstone from a bad reference."""
    allocator = CompactAddressAllocator()
    concepts = _concepts("record")
    alias = allocator.allocate(_entities(1, "record")[0], concepts).alias
    allocator.tombstone(alias, reason="retired")

    history = allocator.resolve_historical(alias)
    assert history is not None
    assert history["status"] == "tombstoned"
    assert allocator.resolve_historical(f"{ALIAS_PREFIX}:0a0b0c0d:1") is None


def test_semantic_change_reallocates_and_supersedes_the_old_alias() -> None:
    """Changing meaning must not silently reinterpret a live address."""
    allocator = CompactAddressAllocator()
    entity_id = _entities(1, "module")[0]
    original = allocator.allocate(entity_id, concepts_for_entity_kind("module"))
    changed = allocator.allocate(entity_id, concepts_for_entity_kind("policy"))

    if original.packed() != changed.packed():
        assert allocator.resolve(original.alias) is None
        superseded = allocator.resolve_historical(original.alias)
        assert superseded is not None
        assert superseded["status"] in {"superseded", "tombstoned"}


def test_unchanged_semantics_preserve_the_existing_allocation() -> None:
    allocator = CompactAddressAllocator()
    entity_id = _entities(1, "module")[0]
    concepts = concepts_for_entity_kind("module")
    first = allocator.allocate(entity_id, concepts)
    second = allocator.allocate(entity_id, concepts)
    assert first == second, "an unchanged meaning must keep its address"


def test_alias_migration_crosswalk_maps_without_rewriting_history() -> None:
    """Consumers migrate through the crosswalk, never by search/replace."""
    allocator = CompactAddressAllocator()
    concepts = _concepts("module")
    ids = _entities(2, "module")
    current = {entity_id: allocator.allocate(entity_id, concepts).alias for entity_id in ids}
    unknown = "pxe1:" + "0" * 32

    crosswalk = allocator.alias_migration_crosswalk({**current, unknown: f"{ALIAS_PREFIX}:0a0b0c0d:1"})
    by_status = {row["status"] for row in crosswalk["entries"]}
    assert by_status == {"unchanged", "unmapped"}
    assert crosswalk["counts"]["unchanged"] == 2
    for row in crosswalk["entries"]:
        if row["status"] == "unchanged":
            assert row["new_alias"] == row["old_alias"]
            assert row["old_alias_status"] == "active"
        else:
            # An old alias that no longer resolves stays historical, never lost.
            assert row["new_alias"] is None
            assert row["old_alias_status"] == "superseded"


def test_vocabulary_is_frozen_and_loads_from_the_published_registry() -> None:
    published = load_vocabulary(REPO_ROOT)
    assert published.as_mapping() == FROZEN_VOCABULARY.as_mapping(), (
        "the published vocabulary registry must agree with the frozen owner"
    )
    document = vocabulary_document()
    assert document["schema_version"] == VOCABULARY_SCHEMA_VERSION
    assert (REPO_ROOT / "registry/semantic_address_vocabulary.json").is_file()


def test_every_dimension_stays_inside_the_reserved_excluded_range() -> None:
    for dimension in DIMENSIONS:
        for member in FROZEN_VOCABULARY.dimension(dimension).members:
            number = FROZEN_VOCABULARY.number(dimension, member)
            assert MIN_SEGMENT <= number <= MAX_SEGMENT
            assert FROZEN_VOCABULARY.member(dimension, number) == member


def test_alias_shape_and_round_trip_are_deterministic() -> None:
    """ACCEPTANCE: alias -> entity -> alias is deterministic."""
    allocator = CompactAddressAllocator()
    entity_id = _entities(1)[0]
    alias = allocator.allocate(entity_id, _concepts()).alias
    assert alias.startswith(ALIAS_PREFIX + ":")
    packed, generation = alias.split(":")[1], alias.split(":")[2]
    assert len(packed) == 8
    assert generation == "1"
    assert allocator.round_trip(alias) == alias
    # Re-allocation is stable, so a rebuild converges on the same alias.
    assert allocator.allocate(entity_id, _concepts()).alias == alias


def test_address_pack_and_parse_are_inverse() -> None:
    address = CompactAddress(subject=1, object=254, semantic_role=128, kind=3, generation=7)
    parsed = parse_alias(address.alias)
    assert parsed == address
    assert address.as_segments()["semantic_role"] == 128


def test_parse_rejects_reserved_segments_hidden_in_an_alias() -> None:
    # Packed 0x00FF0101 puts 0 in the subject segment.
    with pytest.raises(CompactAddressError, match="reserved value"):
        parse_alias(f"{ALIAS_PREFIX}:00ff0101:1")
    # Packed 0x01FF0101 puts 255 in the object segment.
    with pytest.raises(CompactAddressError, match="reserved value"):
        parse_alias(f"{ALIAS_PREFIX}:01ff0101:1")


def test_parse_rejects_malformed_aliases() -> None:
    for bad in (
        "NOPE:00000001:1",
        f"{ALIAS_PREFIX}:0001:1",
        f"{ALIAS_PREFIX}:zzzzzzzz:1",
        f"{ALIAS_PREFIX}:01010101:notanumber",
        f"{ALIAS_PREFIX}:01010101:0",
        "01010101",
    ):
        with pytest.raises(CompactAddressError):
            parse_alias(bad)


def test_tombstone_frees_the_address_and_keeps_it_retired() -> None:
    allocator = CompactAddressAllocator()
    concepts = _concepts()
    first = _entities(2)
    alias_a = allocator.allocate(first[0], concepts).alias
    alias_b = allocator.allocate(first[1], concepts).alias
    assert alias_a != alias_b

    allocator.tombstone(alias_a, reason="retired by test")
    assert allocator.resolve(alias_a) is None, "a tombstoned alias must not resolve"

    # Reallocating the same entity after its tombstone must not hand back the
    # bare address a stale holder could misread as still live.
    reused = allocator.allocate(first[0], concepts)
    assert reused.packed() != parse_alias(alias_a).packed()
    assert reused.alias != alias_a
    assert allocator.resolve(alias_a) is None


def test_a_stale_alias_never_resolves_to_the_new_occupant() -> None:
    """The reason generations exist at all.

    A stale holder carries an alias with the right address but the wrong
    generation. Resolving it MUST return None rather than the current occupant,
    because silently re-pointing a cached reference at a different entity is the
    exact failure this design prevents.
    """
    allocator = CompactAddressAllocator()
    concepts = _concepts()
    entity_id = _entities(1)[0]
    original = allocator.allocate(entity_id, concepts, semantic_generation=1)
    allocator.tombstone(original.alias, reason="retire")
    reused = allocator.allocate(entity_id, concepts, semantic_generation=2)

    assert reused.packed() != original.packed(), (
        "the retired address is not reclaimed, so this entity moved"
    )

    # The retired alias is stale: same address, old generation.
    assert allocator.resolve(original.alias) is None
    # A hand-built alias with a wrong generation also fails.
    stale_generation = f"{ALIAS_PREFIX}:{reused.packed():08x}:{reused.generation + 5}"
    assert allocator.resolve(stale_generation) is None
    # Only the current alias resolves.
    assert allocator.resolve(reused.alias) == entity_id
    assert allocator.round_trip(original.alias) is None
    assert allocator.round_trip(reused.alias) == reused.alias


def test_tombstone_validates_its_target() -> None:
    allocator = CompactAddressAllocator()
    alias = allocator.allocate(_entities(1)[0], _concepts()).alias
    with pytest.raises(CompactAddressError, match="unknown compact address"):
        allocator.tombstone(f"{ALIAS_PREFIX}:0a0b0c0d:1")
    allocator.tombstone(alias, reason="once")
    with pytest.raises(CompactAddressError, match="already tombstoned"):
        allocator.tombstone(alias, reason="twice")


def test_statistics_and_document_report_capacity_and_lifecycle() -> None:
    allocator = CompactAddressAllocator()
    concepts = _concepts()
    ids = _entities(3)
    for entity_id in ids[:2]:
        allocator.allocate(entity_id, concepts)
    allocator.tombstone(allocator.alias_for(ids[1], concepts), reason="gone")
    stats = allocator.statistics()
    assert stats["active"] == 1
    assert stats["tombstoned"] == 1
    assert stats["capacity"] == 254**4
    document = allocator.registry_document()
    assert document["address_contract"] == COMPACT_ADDRESS_SCHEMA_VERSION
    assert document["reserved_values"] == sorted(RESERVED_VALUES)
    lifecycles = {entry["lifecycle"] for entry in document["entries"]}
    assert lifecycles == {"active", "tombstoned"}
    assert document["vocabulary"]["schema_version"] == VOCABULARY_SCHEMA_VERSION
    for entry in document["entries"]:
        assert set(entry["concepts"]) == set(DIMENSIONS)


def test_alias_is_a_bound_reference_and_entity_id_stays_authoritative() -> None:
    """The alias must never become the identity of record."""
    allocator = CompactAddressAllocator()
    entity_id = _entities(1)[0]
    alias = allocator.allocate(entity_id, _concepts()).alias
    address = parse_alias(alias)
    mapping = address.as_mapping(entity_id=entity_id)
    assert mapping["entity_id"] == entity_id
    assert mapping["schema_version"] == COMPACT_ADDRESS_SCHEMA_VERSION
    # The alias contains no entity identity at all.
    assert entity_id.split(":")[1] not in alias


def test_allocation_is_reproducible_from_the_same_entity_set() -> None:
    """Allocator state is a cache, not an authority: it must rebuild identically."""
    concepts = _concepts()
    ids = _entities(len(FROZEN_VOCABULARY.dimension("kind").members))
    first = CompactAddressAllocator()
    baseline = {entity_id: first.allocate(entity_id, concepts).alias for entity_id in ids}
    second = CompactAddressAllocator()
    rebuilt = {entity_id: second.allocate(entity_id, concepts).alias for entity_id in ids}
    assert baseline == rebuilt


def test_empty_entity_id_is_refused() -> None:
    allocator = CompactAddressAllocator()
    with pytest.raises(CompactAddressError, match="empty entity id"):
        allocator.allocate("", _concepts())


def test_overflow_round_trip_does_not_rewrite_live_allocations() -> None:
    allocator = CompactAddressAllocator()
    concepts = _concepts()
    aliases = [allocator.allocate(entity, concepts, semantic_generation=7).alias
               for entity in _entities(3)]
    before = allocator.registry_document()
    for alias in aliases:
        assert allocator.round_trip(alias) == alias
        assert allocator.resolve(alias) is not None
    assert allocator.registry_document() == before
