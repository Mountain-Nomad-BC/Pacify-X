"""Canonical process exit semantics for governed CLI decisions."""

from __future__ import annotations

SUCCESS = 0
EXECUTION_ERROR = 1
RESTRICTED = 2
QUARANTINED = 3
REJECTED = 4
VERIFICATION_FAILED = 5
INSUFFICIENT_EVIDENCE = 6
INVALID_REQUEST = 7
INTEGRITY_FAILURE = 8

_DECISION_CODES = {
    "admit": SUCCESS,
    "restrict": RESTRICTED,
    "quarantine": QUARANTINED,
    "reject": REJECTED,
    "verified": SUCCESS,
    "verification_failed": VERIFICATION_FAILED,
    "insufficient_trusted_evidence": INSUFFICIENT_EVIDENCE,
    "invalid_request": INVALID_REQUEST,
    "evidence_integrity_failure": INTEGRITY_FAILURE,
}


def decision_exit_code(decision: str, *, fallback_valid: bool = False) -> int:
    """Map a governed result state to a stable process exit code."""
    return _DECISION_CODES.get(decision, SUCCESS if fallback_valid else EXECUTION_ERROR)
