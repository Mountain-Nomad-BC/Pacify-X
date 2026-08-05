from __future__ import annotations
from collections import defaultdict
from typing import Any
from ..common.mathx import clamp, entropy


def decayed_trust(
    initial: float,
    age_days: float,
    half_life_days: float,
    validation_boost: float = 0.0,
) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    decay = 0.5 ** (max(0.0, age_days) / half_life_days)
    return clamp(initial * decay + validation_boost)


def contradiction_pressure(claims: list[dict[str, Any]]) -> float:
    if len(claims) < 2:
        return 0.0
    weighted_disagreement = 0.0
    total_weight = 0.0
    for i, left in enumerate(claims):
        for right in claims[i + 1 :]:
            weight = float(left.get("trust", 0.5)) * float(right.get("trust", 0.5))
            total_weight += weight
            if left.get("value") != right.get("value"):
                weighted_disagreement += weight
    return 0.0 if total_weight == 0 else weighted_disagreement / total_weight


def simulate(state: dict[str, Any]) -> dict[str, Any]:
    now_day = float(state.get("now_day", 0))
    records = []
    for record in state.get("records", []):
        age = max(0.0, now_day - float(record.get("validated_day", now_day)))
        trust = decayed_trust(
            float(record.get("trust", 0.5)),
            age,
            float(record.get("half_life_days", 90)),
            float(record.get("validation_boost", 0.0)),
        )
        records.append({**record, "age_days": age, "effective_trust": trust})
    by_subject = defaultdict(list)
    for record in records:
        by_subject[str(record.get("subject", ""))].append(record)
    subjects = []
    for subject, group in sorted(by_subject.items()):
        weights = [r["effective_trust"] for r in group]
        probabilities = [w / sum(weights) for w in weights] if sum(weights) else []
        pressure = contradiction_pressure(group)
        volatility = sum(abs(float(r.get("recent_delta", 0.0))) for r in group) / max(
            1, len(group)
        )
        validation_age = max((r["age_days"] for r in group), default=0.0)
        stability = clamp(
            1.0
            - 0.55 * pressure
            - 0.25 * volatility
            - 0.20 * min(1.0, validation_age / 365.0)
        )
        subjects.append(
            {
                "subject": subject,
                "record_count": len(group),
                "trust_entropy_bits": entropy(probabilities),
                "contradiction_pressure": pressure,
                "volatility": volatility,
                "stability": stability,
                "revalidation_priority": clamp(
                    0.45 * pressure
                    + 0.25 * volatility
                    + 0.20 * (1 - stability)
                    + 0.10 * min(1.0, validation_age / 365)
                ),
            }
        )
    relations = state.get("relations", [])
    coexecution = defaultdict(float)
    for relation in relations:
        if relation.get("type") == "coexecuted":
            pair = tuple(
                sorted([str(relation.get("source")), str(relation.get("target"))])
            )
            coexecution[pair] += float(relation.get("weight", 1.0))
    attractors = [
        {"members": list(pair), "strength": strength}
        for pair, strength in sorted(coexecution.items(), key=lambda x: (-x[1], x[0]))
        if strength >= float(state.get("attractor_threshold", 2.0))
    ]
    return {
        "subjects": subjects,
        "attractors": attractors,
        "highest_revalidation_priorities": sorted(
            subjects, key=lambda x: (-x["revalidation_priority"], x["subject"])
        )[:10],
        "model_note": (
            "Knowledge physics is an explicit operational metaphor. Every output is decomposed "
            "into trust, age, contradictions, volatility, connectivity, and validation evidence."
        ),
    }
