"""Frozen controlled vocabularies for compact semantic addresses (SEM-003).

A compact address is ``Subject.Object.SemanticRole.Kind``.  Each of the four
segments must be *semantically allocated*: the number carries meaning, so two
entities that share a subject share the same subject number, and a reader can
decode the address without holding the allocator.

This module owns that meaning and nothing else.  It declares four hierarchical,
reviewed registries whose members are named concepts, assigns each member a
stable number, and hands those numbers to the allocator.  Two rules matter more
than the specific numbers:

* **The vocabulary is authority.**  Allocation never invents a number.  A concept
  with no registry entry has no address, and the allocator refuses rather than
  hashing the concept into a plausible-looking number.
* **The vocabulary is frozen.**  A number that has ever been issued stays with its
  concept forever.  Concepts retire explicitly; they are never renumbered and
  their number is never handed to a different concept.

The failure this design exists to prevent is the one a digest gives you for free:
``sha256(entity_id)[0] % 254 + 1`` produces a legal, collision-checked,
round-tripping address whose subject segment means nothing at all.  It passes
every structural test while being operationally useless, because nobody can look
at ``PXA1:1a03ff07:1`` and know what it refers to.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

VOCABULARY_SCHEMA_VERSION = "px.semantic-address-vocabulary/1.0"
REGISTRY_RELATIVE = Path("registry/semantic_address_vocabulary.json")

#: The four address dimensions, in hierarchical scope order.  A child is only
#: meaningful inside its parent, so the registries nest: an object family exists
#: within a subject, and a semantic role exists within a subject/object pair.
DIMENSIONS = ("subject", "object", "semantic_role", "kind")

#: 0 is unallocated/unknown and 255 is the reserved meta/escape value.  Neither
#: is ever handed out as a live segment, which is why the usable range is 1..254.
MIN_SEGMENT = 1
MAX_SEGMENT = 254

#: The capacity of a single dimension.  A sibling set larger than this cannot be
#: allocated and must be split or merged in the taxonomy first; it must never be
#: allowed to overflow and wrap, because wrapping silently re-points live
#: addresses at different concepts.
DIMENSION_CAPACITY = MAX_SEGMENT - MIN_SEGMENT + 1


class VocabularyError(ValueError):
    """A controlled vocabulary is malformed, frozen, or out of capacity."""


@dataclass(frozen=True, slots=True)
class Dimension:
    """One hierarchical dimension and the concepts allocated inside it."""

    name: str
    members: tuple[str, ...]

    def index_of(self, member: str) -> int | None:
        try:
            return self.members.index(member)
        except ValueError:
            return None

    def number_of(self, member: str) -> int:
        """The allocated number for a member, or refuse.

        Refusing rather than falling back to a hash is the whole point: a
        concept missing from the registry has no address until a human reviews
        it into the registry.
        """
        if type(member) is not str or not member.strip():
            raise VocabularyError(
                f"{self.name} requires a named concept, not an empty value"
            )
        index = self.index_of(member)
        if index is None:
            raise VocabularyError(
                f"{self.name} concept {member!r} is not in the frozen vocabulary"
            )
        return MIN_SEGMENT + index

    def member_of(self, number: int) -> str | None:
        if type(number) is not int or isinstance(number, bool):
            raise VocabularyError("a decoded segment must be an integer")
        index = number - MIN_SEGMENT
        # A legal number with no member decodes to None rather than raising.
        # Disambiguation walks the kind dimension across its whole 1..254 range,
        # so a registry with fewer kinds than addresses WILL see unassigned
        # numbers, and an address written against a larger vocabulary will too.
        # None means "this number carries no reviewed meaning", which the caller
        # must surface; an IndexError would crash a historical reader instead.
        if index < 0 or index >= len(self.members):
            return None
        return self.members[index]

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "member_count": len(self.members),
            "capacity": DIMENSION_CAPACITY,
            "members": [
                {"member": member, "number": MIN_SEGMENT + index}
                for index, member in enumerate(self.members)
            ],
        }


def _require_unique(values: Iterable[str], *, dimension: str) -> tuple[str, ...]:
    members = tuple(values)
    for member in members:
        if type(member) is not str or not member.strip():
            raise VocabularyError(
                f"{dimension} members must be bounded nonempty names"
            )
    if len(set(members)) != len(members):
        duplicates = sorted(
            {member for member in members if members.count(member) > 1}
        )
        raise VocabularyError(
            f"{dimension} repeats members: {', '.join(duplicates)}"
        )
    if len(members) > DIMENSION_CAPACITY:
        raise VocabularyError(
            f"{dimension} has {len(members)} members but only {DIMENSION_CAPACITY} "
            "addresses exist; split or merge the taxonomy before allocating"
        )
    return members


# ---------------------------------------------------------------------------
# The registry is the single authority.
#
# This module used to hardcode the four dimensions here while
# ``registry/semantic_address_vocabulary.json`` carried the census-derived set.
# That produced two sources of truth, and the drift surfaced only as a failing
# equality test - exactly the failure a "frozen" vocabulary exists to prevent.
#
# The dimensions are therefore LOADED from the registry, which is generated from
# the census by ``.engineering-bootstrap/tmp/build_vocabulary.py``. There is no
# hand-written list left here to disagree with it. ``load_vocabulary`` is the one
# place that parses and validates the registry; a caller with an explicit
# vocabulary (a test, a dry run) may still construct one directly.
# ---------------------------------------------------------------------------



class SemanticVocabulary:
    """The four frozen dimensions, and nothing else.

    Immutable after construction.  Adding a concept is a reviewed edit to the
    registry followed by a new semantic generation, never an in-place mutation,
    so an address issued under generation N keeps its meaning forever.
    """

    def __init__(self, dimensions: Mapping[str, Iterable[str]]) -> None:
        if set(dimensions) != set(DIMENSIONS):
            raise VocabularyError(
                "vocabulary must declare exactly the four address dimensions"
            )
        self._dimensions: dict[str, Dimension] = {}
        for name in DIMENSIONS:
            members = _require_unique(dimensions[name], dimension=name)
            if not members:
                raise VocabularyError(f"{name} vocabulary must not be empty")
            self._dimensions[name] = Dimension(name=name, members=members)

    def dimension(self, name: str) -> Dimension:
        if name not in self._dimensions:
            raise VocabularyError(f"{name!r} is not an address dimension")
        return self._dimensions[name]

    def number(self, dimension: str, member: str) -> int:
        return self.dimension(dimension).number_of(member)

    def member(self, dimension: str, number: int) -> str | None:
        return self.dimension(dimension).member_of(number)

    def decode(self, segments: Mapping[str, int]) -> dict[str, str | None]:
        """Segments back to concepts; ``None`` where a number has no concept.

        An address written under an older vocabulary can decode to ``None`` for a
        concept that has since been retired.  Returning ``None`` rather than
        raising keeps historical records readable, and the caller decides whether
        an undecodable segment is acceptable.
        """
        decoded: dict[str, str | None] = {}
        for name in DIMENSIONS:
            if name not in segments:
                raise VocabularyError(f"address is missing the {name} segment")
            decoded[name] = self.member(name, segments[name])
        return decoded

    def encode(self, concepts: Mapping[str, str]) -> dict[str, int]:
        """Concepts to segments, refusing any concept outside the vocabulary."""
        if set(concepts) != set(DIMENSIONS):
            raise VocabularyError("an address requires exactly four dimensions")
        return {
            name: self.number(name, concepts[name]) for name in DIMENSIONS
        }

    def capacity_report(self) -> dict[str, object]:
        return {
            "dimensions": [self._dimensions[name].as_mapping() for name in DIMENSIONS],
            "smallest_headroom": min(
                DIMENSION_CAPACITY - len(self._dimensions[name].members)
                for name in DIMENSIONS
            ),
        }

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_version": VOCABULARY_SCHEMA_VERSION,
            "segment_range": [MIN_SEGMENT, MAX_SEGMENT],
            "dimension_capacity": DIMENSION_CAPACITY,
            "dimensions": [self._dimensions[name].as_mapping() for name in DIMENSIONS],
            "capacity_report": self.capacity_report(),
        }


def vocabulary_document() -> dict[str, object]:
    """The serializable projection written to the registry."""
    return FROZEN_VOCABULARY.as_mapping()


def load_vocabulary(root: Path) -> SemanticVocabulary:
    """Read the published registry.

    This compares content, not just schema version: a registry edited on disk
    without changing the owner would otherwise silently redefine every live
    address, which is precisely the failure a frozen vocabulary rules out.
    """
    path = Path(root) / REGISTRY_RELATIVE
    if not path.is_file():
        raise VocabularyError(
            f"the published vocabulary registry "
            f"{REGISTRY_RELATIVE.as_posix()} is absent"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VocabularyError("vocabulary registry must be an object")
    if document.get("schema_version") != VOCABULARY_SCHEMA_VERSION:
        raise VocabularyError("vocabulary registry schema version is not current")
    published: dict[str, tuple[str, ...]] = {}
    for record in document.get("dimensions", []):
        if not isinstance(record, dict) or not isinstance(record.get("members"), list):
            raise VocabularyError("vocabulary registry dimensions are malformed")
        name = str(record.get("name") or "")
        members: list[str] = []
        for entry in record["members"]:
            if not isinstance(entry, dict) or type(entry.get("member")) is not str:
                raise VocabularyError("vocabulary member entries are malformed")
            number = entry.get("number")
            expected = MIN_SEGMENT + len(members)
            if number != expected:
                raise VocabularyError(
                    f"{name} member {entry['member']!r} is numbered {number}, "
                    f"expected {expected}; a frozen vocabulary cannot renumber"
                )
            members.append(entry["member"])
        published[name] = tuple(members)
    return SemanticVocabulary(published)


#: The single authority: the published registry. Nothing here restates it.
FROZEN_VOCABULARY = load_vocabulary(Path(__file__).resolve().parents[1])
