"""Canonical entity coverage and ambiguity ledger - implements punch card SEM-006.

SEM-006's acceptance is "zero unexplained/unowned source objects at remap gate"
and "ambiguity remains explicit rather than guessed". This module is the owner
that makes both checkable instead of aspirational.

Why a ledger at all
-------------------
Before this existed, "is every source object classified?" had no answer. The
census counted objects; nothing recorded what happened to each one. An object
that nobody claimed was indistinguishable from an object that was deliberately
excluded, and an ambiguous classification looked exactly like an accepted one.
A rename built on that difference would silently drop or misroute whichever
objects nobody happened to notice.

Dispositions
------------
Every observed object carries exactly one disposition:

``accepted``
    Classified, owned, and safe to remap.
``unresolved``
    Seen but not classified. An explicit "I do not know", never a default.
``ambiguous``
    More than one classification fits with comparable support. Recorded with the
    rivals so a human decides, rather than the code picking the highest score.
``conflicting``
    Two observations assert incompatible things about the same object.
``external``
    Not owned by this project. Legitimate, but must be declared so it is never
    mistaken for an unowned internal object.
``historical``
    Superseded or tombstoned; retained as fact, excluded from remap.
``intentionally_unclassified``
    A human declared this out of scope. Distinct from ``unresolved``: one is a
    decision, the other is a gap.

The gap gate
------------
High-risk ambiguity BLOCKS the migration it would affect; low-risk descriptive
uncertainty goes to review. That split matters: a wrong object family is a
silent routing bug, while an unclear docstring label is cosmetic. Blocking the
whole build on the second kind trains people to ignore the gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

COVERAGE_SCHEMA_VERSION = "px.semantic-coverage/1.0"
ENTITY_INDEX_RELATIVE = "registry/semantic_entity_index.json"
COVERAGE_EVIDENCE_RELATIVE = "evidence/v1x/semantic-coverage.json"

ACCEPTED = "accepted"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"
CONFLICTING = "conflicting"
EXTERNAL = "external"
HISTORICAL = "historical"
INTENTIONALLY_UNCLASSIFIED = "intentionally_unclassified"
EXCLUDED = "excluded"

DISPOSITIONS = (
    ACCEPTED,
    UNRESOLVED,
    AMBIGUOUS,
    CONFLICTING,
    EXTERNAL,
    HISTORICAL,
    INTENTIONALLY_UNCLASSIFIED,
    EXCLUDED,
)

#: Dispositions that represent a decision rather than a gap. Only UNRESOLVED,
#: AMBIGUOUS and CONFLICTING are missing knowledge; the rest are accounted for.
#: EXCLUDED is a decision: the corpus owner deliberately did not admit the
#: object, and the reason is preserved so the exclusion stays auditable rather
#: than being silent population loss.
DECIDED = frozenset(
    {ACCEPTED, EXTERNAL, HISTORICAL, INTENTIONALLY_UNCLASSIFIED, EXCLUDED}
)

#: Dispositions that mean this project does not know what the object is. These
#: are the ones the remap gate counts.
UNEXPLAINED = frozenset({UNRESOLVED, AMBIGUOUS, CONFLICTING})

#: Dispositions that may still be remapped automatically.
REMAPPABLE = frozenset(
    {ACCEPTED, EXTERNAL, HISTORICAL, INTENTIONALLY_UNCLASSIFIED, EXCLUDED}
)


class CoverageError(ValueError):
    """The coverage ledger is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class Observation:
    """One observed object and what is currently known about it."""

    object_id: str
    disposition: str = UNRESOLVED
    owner: str | None = None
    classification: str | None = None
    rivals: tuple[str, ...] = ()
    risk: str = "low"
    note: str | None = None

    def __post_init__(self) -> None:
        if type(self.object_id) is not str or not self.object_id.strip():
            raise CoverageError("an observation requires an object identity")
        if len(self.object_id) > 512:
            raise CoverageError("object identity is bounded")
        if self.disposition not in DISPOSITIONS:
            raise CoverageError(
                f"{self.disposition!r} is not a coverage disposition; "
                f"expected one of {', '.join(DISPOSITIONS)}"
            )
        if self.rivals and self.disposition != AMBIGUOUS:
            raise CoverageError(
                "only an ambiguous observation may carry rival classifications"
            )
        if self.risk not in {"low", "high"}:
            raise CoverageError("risk must be low or high")
        if self.disposition == ACCEPTED and not self.owner:
            raise CoverageError(
                "an accepted object must name its owner; an unowned accepted "
                "object is exactly the gap this ledger exists to close"
            )

    @property
    def blocking(self) -> bool:
        """Does this gap hold up the remap it affects?

        Only high-risk ambiguity blocks. Low-risk descriptive uncertainty is
        routed to review instead, because a gate that blocks the whole build on
        a cosmetic unknown gets ignored, and an ignored gate protects nothing.
        """
        return self.disposition in UNEXPLAINED and self.risk == "high"

    @property
    def explained(self) -> bool:
        return self.disposition in DECIDED

    def as_mapping(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "disposition": self.disposition,
            "owner": self.owner,
            "classification": self.classification,
            "rivals": list(self.rivals),
            "risk": self.risk,
            "blocking": self.blocking,
            "note": self.note,
        }


@dataclass
class CoverageLedger:
    """The canonical coverage index for a corpus of observed objects."""

    observations: dict[str, Observation] = field(default_factory=dict)

    def record(self, observation: Observation) -> Observation:
        existing = self.observations.get(observation.object_id)
        if existing is not None and existing.disposition != observation.disposition:
            raise CoverageError(
                f"{observation.object_id} is already {existing.disposition}; "
                f"a disposition change must go through the remap gate, not a "
                f"silent re-record"
            )
        self.observations[observation.object_id] = observation
        return observation

    def extend(self, observations: Iterable[Observation]) -> None:
        for observation in observations:
            self.record(observation)

    # -- queries ---------------------------------------------------------------

    def by_disposition(self, disposition: str) -> list[Observation]:
        return [
            observation for observation in self.observations.values()
            if observation.disposition == disposition
        ]

    def counts(self) -> dict[str, int]:
        counts = {disposition: 0 for disposition in DISPOSITIONS}
        for observation in self.observations.values():
            counts[observation.disposition] += 1
        return counts

    def unexplained(self) -> list[Observation]:
        """Objects this project does not have an answer for."""
        return sorted(
            (observation for observation in self.observations.values()
             if not observation.explained),
            key=lambda observation: observation.object_id,
        )

    def blocking(self) -> list[Observation]:
        """High-risk gaps that must hold up the migration they affect."""
        return sorted(
            (observation for observation in self.observations.values()
             if observation.blocking),
            key=lambda observation: observation.object_id,
        )

    def review_queue(self) -> list[Observation]:
        """Low-risk gaps, routed to review rather than blocking."""
        return sorted(
            (observation for observation in self.observations.values()
             if not observation.explained and not observation.blocking),
            key=lambda observation: observation.object_id,
        )

    # -- gates -----------------------------------------------------------------

    def remap_gate(self) -> dict[str, Any]:
        """The zero-unexplained-unowned gate.

        ``passed`` requires no unexplained object at all. ``blocks`` names the
        high-risk subset that must be resolved before the specific migrations it
        would corrupt; those are reported even when the overall gate passes,
        because a corpus can have only low-risk gaps left and still need the
        list.
        """
        unexplained = self.unexplained()
        blocking = self.blocking()
        return {
            "unexplained_count": len(unexplained),
            "blocking_count": len(blocking),
            "review_count": len(self.review_queue()),
            # Every unexplained object is reported, not just a count, so a human
            # can act on the list instead of re-deriving it.
            "unexplained": [item.object_id for item in unexplained],
            "blocking": [item.object_id for item in blocking],
            "passed": not unexplained,
        }

    def assert_no_high_risk_gaps(self) -> None:
        blocking = self.blocking()
        if blocking:
            raise CoverageError(
                "high-risk semantic assignments remain unresolved: "
                + ", ".join(item.object_id for item in blocking)
            )

    # -- projections -----------------------------------------------------------

    def entity_index(self) -> dict[str, Any]:
        """The accepted-entity index: what a rename may act on."""
        return {
            "schema_version": COVERAGE_SCHEMA_VERSION,
            "coverage_evidence": COVERAGE_EVIDENCE_RELATIVE,
            "counts": self.counts(),
            "entities": [
                observation.as_mapping()
                for observation in sorted(self.observations.values(), key=lambda o: o.object_id)
                if observation.disposition in REMAPPABLE
            ],
        }

    def evidence_document(self) -> dict[str, Any]:
        """The full ledger, including the gaps. Gaps are the point."""
        return {
            "schema_version": COVERAGE_SCHEMA_VERSION,
            "entity_index": ENTITY_INDEX_RELATIVE,
            "counts": self.counts(),
            "gate": self.remap_gate(),
            "observations": [
                observation.as_mapping()
                for observation in sorted(self.observations.values(), key=lambda o: o.object_id)
            ],
        }


def ledger_from_observations(observations: Iterable[Observation]) -> CoverageLedger:
    ledger = CoverageLedger()
    ledger.extend(observations)
    return ledger