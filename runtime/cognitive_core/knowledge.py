"""Scoped belief ledger and bounded truth-maintenance projection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .common import clamp, stable_hash


def _parse_time(raw: object, field: str) -> datetime | None:
    if raw is None or raw == "":
        return None
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Belief:
    belief_id: str
    subject: str
    predicate: str
    value: Any
    scope: str
    valid_from: datetime | None
    valid_to: datetime | None
    confidence: float
    supports: tuple[str, ...]
    attacks: tuple[str, ...]
    dependencies: tuple[str, ...]
    status: str = "candidate"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Belief":
        belief_id = str(value.get("id", "")).strip()
        subject = str(value.get("subject", "")).strip()
        predicate = str(value.get("predicate", "")).strip()
        if not belief_id or not subject or not predicate:
            raise ValueError("belief id, subject, and predicate are required")
        confidence = float(value.get("confidence", 0.5))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"belief {belief_id}: confidence must be in [0, 1]")
        valid_from = _parse_time(
            value.get("valid_from"), f"belief {belief_id} valid_from"
        )
        valid_to = _parse_time(value.get("valid_to"), f"belief {belief_id} valid_to")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValueError(f"belief {belief_id}: valid_to precedes valid_from")
        return cls(
            belief_id,
            subject,
            predicate,
            value.get("value"),
            str(value.get("scope", "global")),
            valid_from,
            valid_to,
            confidence,
            tuple(map(str, value.get("supports", ()))),
            tuple(map(str, value.get("attacks", ()))),
            tuple(map(str, value.get("dependencies", ()))),
            str(value.get("status", "candidate")),
        )


def _overlap(left: Belief, right: Belief) -> bool:
    start = max(filter(None, (left.valid_from, right.valid_from)), default=None)
    end = min(filter(None, (left.valid_to, right.valid_to)), default=None)
    return not (start and end and end < start)


class BeliefLedger:
    def __init__(self, beliefs: Sequence[Belief]) -> None:
        ids = [belief.belief_id for belief in beliefs]
        if len(ids) != len(set(ids)):
            raise ValueError("belief IDs must be unique")
        self.beliefs = {belief.belief_id: belief for belief in beliefs}
        for belief in beliefs:
            unknown = (
                set(belief.supports) | set(belief.attacks) | set(belief.dependencies)
            ) - set(ids)
            if unknown:
                raise ValueError(
                    f"belief {belief.belief_id}: unknown links {sorted(unknown)}"
                )
            if belief.belief_id in set(belief.supports) | set(belief.attacks) | set(
                belief.dependencies
            ):
                raise ValueError(f"belief {belief.belief_id}: self-links are forbidden")

    def project(
        self, *, as_of: datetime | None = None, scope: str | None = None
    ) -> dict[str, Any]:
        now = as_of or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("as_of must include an explicit timezone")
        now = now.astimezone(timezone.utc)
        active = {
            key: belief
            for key, belief in self.beliefs.items()
            if (scope is None or belief.scope == scope)
            and (belief.valid_from is None or belief.valid_from <= now)
            and (belief.valid_to is None or now <= belief.valid_to)
            and belief.status not in {"revoked", "superseded"}
        }
        scores = {key: belief.confidence for key, belief in active.items()}
        converged = True
        iterations = 0
        # Bounded fixed-point influence. An isolated belief retains its base confidence.
        for iteration in range(1, 51):
            iterations = iteration
            updated = dict(scores)
            for key, belief in active.items():
                support = (
                    sum(scores.get(item, 0.0) for item in belief.supports)
                    / len(belief.supports)
                    if belief.supports
                    else 0.0
                )
                attack = (
                    sum(scores.get(item, 0.0) for item in belief.attacks)
                    / len(belief.attacks)
                    if belief.attacks
                    else 0.0
                )
                dependency = min(
                    (scores.get(item, 0.0) for item in belief.dependencies), default=1.0
                )
                strengthened = belief.confidence + 0.25 * support * (
                    1.0 - belief.confidence
                )
                weakened = strengthened - 0.35 * attack * strengthened
                updated[key] = clamp(weakened * dependency)
            delta = max(
                (abs(updated[key] - scores[key]) for key in scores), default=0.0
            )
            scores = updated
            if delta < 1e-9:
                break
        else:
            converged = False

        grouped: dict[tuple[str, str, str], list[Belief]] = defaultdict(list)
        for belief in active.values():
            grouped[(belief.subject, belief.predicate, belief.scope)].append(belief)
        contradictions = []
        for key, group in grouped.items():
            for index, left in enumerate(group):
                for right in group[index + 1 :]:
                    if left.value != right.value and _overlap(left, right):
                        contradictions.append(
                            {
                                "subject": key[0],
                                "predicate": key[1],
                                "scope": key[2],
                                "left": left.belief_id,
                                "right": right.belief_id,
                                "left_effective_confidence": scores[left.belief_id],
                                "right_effective_confidence": scores[right.belief_id],
                                "resolution": "preserve_conflict_until_scope_time_or_evidence_resolves",
                            }
                        )
        records = [
            {
                "id": belief.belief_id,
                "subject": belief.subject,
                "predicate": belief.predicate,
                "value": belief.value,
                "scope": belief.scope,
                "status": belief.status,
                "base_confidence": belief.confidence,
                "effective_confidence": scores[belief.belief_id],
                "supports": list(belief.supports),
                "attacks": list(belief.attacks),
                "dependencies": list(belief.dependencies),
            }
            for belief in sorted(active.values(), key=lambda item: item.belief_id)
        ]
        result = {
            "valid": converged,
            "as_of": now.isoformat(),
            "scope": scope,
            "beliefs": records,
            "contradictions": contradictions,
            "fixed_point_converged": converged,
            "iterations": iterations,
            "warning": "Confidence influence is a bounded policy heuristic; it is not a substitute for calibrated probability or source-specific likelihood models.",
        }
        return {**result, "result_sha256": stable_hash(result)}


def project(payload: Mapping[str, Any]) -> dict[str, Any]:
    beliefs = tuple(Belief.from_mapping(item) for item in payload.get("beliefs", ()))
    as_of = _parse_time(payload.get("as_of"), "as_of")
    return BeliefLedger(beliefs).project(
        as_of=as_of, scope=str(payload["scope"]) if payload.get("scope") else None
    )
