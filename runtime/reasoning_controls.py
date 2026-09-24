"""Bounded reasoning controls that preserve independence and mandatory context."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
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


def decide_context_compaction(
    *, current_context_tokens: int, context_window_tokens: int,
    observed_growth_tokens_per_request: float, observed_requests_per_completed_step: float,
    unfinished_steps: int, cache_rewrite_ratio: float = 1.0,
    retained_fraction_after_compaction: float = 0.55, previous_compactions: int = 0,
    emergency_fraction: float = 0.90, at_plan_step_boundary: bool = True,
) -> dict[str, object]:
    """Cost-gated context compaction; routine compaction waits for a plan boundary."""
    if type(at_plan_step_boundary) is not bool:
        raise ValueError("plan-step boundary flag must be boolean")
    numeric = [observed_growth_tokens_per_request, observed_requests_per_completed_step, cache_rewrite_ratio, retained_fraction_after_compaction, emergency_fraction]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in numeric):
        raise ValueError("context compaction inputs must be finite numbers")
    if type(current_context_tokens) is not int or isinstance(current_context_tokens, bool) or current_context_tokens < 0 or type(context_window_tokens) is not int or isinstance(context_window_tokens, bool) or context_window_tokens <= 0 or current_context_tokens > context_window_tokens:
        raise ValueError("context sizes are invalid")
    if type(unfinished_steps) is not int or isinstance(unfinished_steps, bool) or unfinished_steps < 0 or type(previous_compactions) is not int or isinstance(previous_compactions, bool) or previous_compactions < 0:
        raise ValueError("context compaction counts are invalid")
    if not 0 < retained_fraction_after_compaction < 1 or not 0 < emergency_fraction <= 1 or cache_rewrite_ratio < 0:
        raise ValueError("context compaction policy is invalid")
    emergency = current_context_tokens >= context_window_tokens * emergency_fraction
    estimated_requests = max(0.0, float(observed_requests_per_completed_step)) * unfinished_steps
    growth = float(observed_growth_tokens_per_request)
    if growth > 0:
        estimated_requests = min(estimated_requests, max(0.0, (context_window_tokens - current_context_tokens) / growth))
    removable = current_context_tokens * (1.0 - retained_fraction_after_compaction)
    projected_savings = removable * estimated_requests
    rewrite_cost = current_context_tokens * max(0.0, float(cache_rewrite_ratio))
    margin = 1.10 + min(previous_compactions, 5) * 0.20
    economic = projected_savings > rewrite_cost * margin and removable > 0
    compact = emergency or (at_plan_step_boundary is True and economic)
    reason = "near_context_limit" if emergency else "projected_savings_clear_gate" if compact else "not_plan_boundary" if economic and at_plan_step_boundary is not True else "rewrite_cost_not_recovered"
    body = {"schema_version":"px.context-compaction-decision/1.0", "compact":compact, "reason":reason, "at_plan_step_boundary":at_plan_step_boundary is True, "estimated_remaining_requests":round(estimated_requests,6), "projected_repeated_input_tokens":round(projected_savings,6), "estimated_rewrite_cost_tokens":round(rewrite_cost,6), "savings_margin":round(margin,6), "emergency":emergency, "authority_granted":False}
    return {**body, "decision_sha256": _stable(body)}
