"""Bounded reasoning controls that preserve independence and mandatory context."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Iterable, Mapping, Sequence


MANDATORY_COMMUNICATION_CATEGORIES = frozenset(
    {"failure", "uncertainty", "authority", "recovery", "evidence"}
)


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def run_independent_hypothesis_panel(
    branches: Sequence[Mapping[str, object]],
    *,
    convergence_threshold: float = 0.75,
    max_rounds: int = 3,
) -> dict[str, object]:
    """Critique isolated hypotheses and converge only when evidence supports it.

    The function consumes observable branch artifacts. It neither requests nor
    records private reasoning traces.
    """
    if not 2 <= len(branches) <= 12:
        raise ValueError("an independent panel requires two through twelve branches")
    if not 0.5 <= convergence_threshold <= 1.0:
        raise ValueError("convergence_threshold must be between 0.5 and 1.0")
    if not 1 <= max_rounds <= 10:
        raise ValueError("max_rounds must be between one and ten")

    normalized: list[dict[str, object]] = []
    branch_ids: set[str] = set()
    evidence_owners: dict[str, set[str]] = {}
    errors: list[str] = []
    for branch in branches:
        branch_id = str(branch.get("branch_id", "")).strip()
        conclusion = str(branch.get("conclusion", "")).strip()
        evidence = tuple(sorted(set(map(str, branch.get("evidence_ids", ())))))
        confidence = float(branch.get("confidence", 0.0))
        if not branch_id or branch_id in branch_ids:
            raise ValueError("branch IDs must be non-empty and unique")
        branch_ids.add(branch_id)
        if branch.get("isolated") is not True:
            errors.append(f"{branch_id}: branch was not independently isolated")
        if not conclusion:
            errors.append(f"{branch_id}: conclusion missing")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("branch confidence must be between zero and one")
        if not evidence:
            errors.append(f"{branch_id}: evidence missing")
        for evidence_id in evidence:
            evidence_owners.setdefault(evidence_id, set()).add(branch_id)
        normalized.append(
            {
                "branch_id": branch_id,
                "conclusion": conclusion,
                "confidence": confidence,
                "evidence_ids": evidence,
                "artifact_sha256": str(branch.get("artifact_sha256", "")),
            }
        )

    correlated = sorted(
        evidence_id
        for evidence_id, owners in evidence_owners.items()
        if len(owners) == len(branches)
    )
    if correlated:
        errors.append(
            "all branches rely on the same evidence; independence is not established"
        )

    totals: Counter[str] = Counter()
    for branch in normalized:
        totals[str(branch["conclusion"])] += max(float(branch["confidence"]), 0.01)
    total_weight = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    leading, leading_weight = ranked[0]
    support = leading_weight / total_weight if total_weight else 0.0
    converged = not errors and support >= convergence_threshold
    dissent = [
        {
            "branch_id": branch["branch_id"],
            "conclusion": branch["conclusion"],
            "confidence": branch["confidence"],
            "evidence_ids": list(branch["evidence_ids"]),
        }
        for branch in normalized
        if branch["conclusion"] != leading
    ]
    critic = {
        "independent": True,
        "method": "observable-artifact-consistency-and-evidence-separation",
        "private_reasoning_requested": False,
        "findings": errors,
        "shared_evidence_ids": correlated,
    }
    return {
        "valid": not errors,
        "converged": converged,
        "selected_conclusion": leading if converged else None,
        "leading_support": round(support, 6),
        "threshold": convergence_threshold,
        "rounds_used": 1,
        "max_rounds": max_rounds,
        "branches": normalized,
        "dissent": dissent,
        "critic": critic,
        "panel_sha256": _stable({"branches": normalized, "critic": critic}),
        "authority_granted": False,
    }


def compact_communication(
    messages: Iterable[Mapping[str, object]],
    *,
    max_items: int,
    mandatory_categories: Iterable[str] = MANDATORY_COMMUNICATION_CATEGORIES,
) -> dict[str, object]:
    """Compress repeat messages while preserving mandatory safety information."""
    if max_items < 1:
        raise ValueError("max_items must be positive")
    required = frozenset(map(str, mandatory_categories))
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for message in messages:
        identifier = str(message.get("id", "")).strip()
        category = str(message.get("category", "")).strip()
        text = str(message.get("text", "")).strip()
        if not identifier or identifier in seen_ids or not category or not text:
            raise ValueError("messages require unique IDs, category, and text")
        seen_ids.add(identifier)
        rows.append(
            {
                "id": identifier,
                "category": category,
                "text": text,
                "evidence_ids": sorted(set(map(str, message.get("evidence_ids", ())))),
                "repeat_key": str(message.get("repeat_key", text)).strip().casefold(),
            }
        )

    mandatory = [row for row in rows if row["category"] in required]
    if len(mandatory) > max_items:
        return {
            "valid": False,
            "decision": "budget_insufficient",
            "items": mandatory,
            "mandatory_count": len(mandatory),
            "max_items": max_items,
            "dropped": [],
            "errors": ["communication budget cannot contain all mandatory records"],
        }

    selected = list(mandatory)
    selected_ids = {str(row["id"]) for row in selected}
    optional = [row for row in rows if row["id"] not in selected_ids]
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in optional:
        groups.setdefault((str(row["category"]), str(row["repeat_key"])), []).append(
            row
        )
    summaries: list[dict[str, object]] = []
    for (category, repeat_key), group in sorted(groups.items()):
        first = group[0]
        summaries.append(
            {
                "id": str(first["id"]),
                "category": category,
                "text": str(first["text"]),
                "evidence_ids": sorted(
                    {item for row in group for item in row["evidence_ids"]}
                ),
                "repeat_key": repeat_key,
                "repeat_count": len(group),
                "source_ids": [str(row["id"]) for row in group],
            }
        )
    selected.extend(summaries[: max_items - len(selected)])
    retained_source_ids = {
        source for row in selected for source in row.get("source_ids", [str(row["id"])])
    }
    dropped = [str(row["id"]) for row in rows if row["id"] not in retained_source_ids]
    return {
        "valid": True,
        "decision": "compacted",
        "items": selected,
        "original_count": len(rows),
        "retained_count": len(selected),
        "mandatory_count": len(mandatory),
        "max_items": max_items,
        "dropped": dropped,
        "compression_sha256": _stable(selected),
        "authority_granted": False,
    }
