"""Independent, evidence-backed postcondition verification."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class VerificationDecision:
    status: str
    failed_checks: tuple[str, ...]
    warnings: tuple[str, ...]
    approved_evidence_ids: tuple[str, ...]


def verify(
    postconditions: Mapping[str, bool],
    evidence: Sequence[Mapping[str, object]],
    *,
    policy_allowed: bool,
    executor_claimed_complete: bool,
) -> VerificationDecision:
    failed = sorted(name for name, passed in postconditions.items() if not passed)
    current = sorted(
        str(item["id"])
        for item in evidence
        if item.get("status") == "current" and item.get("valid") is True and item.get("id")
    )
    warnings: list[str] = []
    if not policy_allowed:
        return VerificationDecision("blocked", ("policy did not allow outcome",), (), tuple(current))
    if not postconditions:
        return VerificationDecision("failed", ("no postconditions declared",), (), tuple(current))
    if failed:
        if executor_claimed_complete:
            warnings.append("executor completion claim contradicted by postconditions")
        return VerificationDecision("failed", tuple(failed), tuple(warnings), tuple(current))
    if not current:
        return VerificationDecision("partial", (), ("postconditions lack current valid evidence",), ())
    if not executor_claimed_complete:
        warnings.append("postconditions passed although executor did not claim completion")
    return VerificationDecision("verified", (), tuple(warnings), tuple(current))

