"""Deterministic capability admission decisions from reviewed metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

KNOWN_EFFECTS = {"read_local", "trace_write", "write_workspace", "install_tool", "network", "run_service", "secret_access", "migration", "destructive"}
HIGH_RISK_EFFECTS = {"install_tool", "network", "run_service", "secret_access", "migration", "destructive"}


@dataclass(frozen=True)
class AdmissionDecision:
    disposition: str
    reasons: tuple[str, ...]
    allowed_environment: str
    promotion_state: str


def review(manifest: Mapping[str, object], evidence: Mapping[str, object]) -> AdmissionDecision:
    fatal: list[str] = []
    restrictions: list[str] = []
    required = {"id", "version", "owner", "provides", "consumes", "effects", "dependencies"}
    missing = sorted(required - set(manifest))
    if missing:
        fatal.append("missing manifest fields: " + ", ".join(missing))
    effects = set(manifest.get("effects", ()))
    unknown = sorted(effects - KNOWN_EFFECTS)
    if unknown:
        fatal.append("unknown effects: " + ", ".join(unknown))
    if not evidence.get("provenance_verified"):
        fatal.append("provenance is not verified")
    if not evidence.get("license_reviewed"):
        fatal.append("license is not reviewed")
    if evidence.get("malicious_or_unsafe"):
        return AdmissionDecision("reject", ("unsafe behavior evidence",), "none", "rejected")
    if fatal:
        return AdmissionDecision("quarantine", tuple(fatal), "metadata-review-only", "candidate")
    if not evidence.get("tests_passed"):
        restrictions.append("validation tests have not passed")
    if effects & HIGH_RISK_EFFECTS:
        restrictions.append("high-risk effects require an approved adapter and runtime approval")
    if restrictions:
        return AdmissionDecision("restrict", tuple(restrictions), "sandbox-or-read-only", "admitted_restricted")
    return AdmissionDecision("admit", (), "governed-runtime", "admitted")

