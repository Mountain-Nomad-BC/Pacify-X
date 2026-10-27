"""Gremlin health states and graceful degradation.

The core rule: **failure of the jailer must reduce the gremlin's freedom, not
increase it** (GN-INV-007, GN-INV-008). Every degradation maps to a concrete
reduction of the protected workload's capability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

SCHEMA_VERSION = "px.gremlin-health/1.0"

HEALTH_STATES = (
    "HEALTHY",
    "DEGRADED",
    "PARTIAL_OBSERVATION",
    "PARTIAL_ENFORCEMENT",
    "UNTRUSTED_TELEMETRY",
    "POLICY_INTEGRITY_FAILURE",
    "CONTROL_INTEGRITY_FAILURE",
    "OFFLINE",
    "RECOVERING",
)

# Degradation matrix (plan section 21): each condition maps to a workload
# capability reduction. A workload never gains freedom from a GN failure.
DEGRADATION_MATRIX = {
    "analytics_unavailable": ("DEGRADED", "continue_deterministic_policy_only"),
    "llm_evaluator_unavailable": ("DEGRADED", "continue_without_ai_analysis"),
    "network_observer_unavailable": ("PARTIAL_OBSERVATION", "revoke_network"),
    "filesystem_observer_unavailable": ("PARTIAL_OBSERVATION", "restrict_writes"),
    "policy_integrity_uncertain": ("POLICY_INTEGRITY_FAILURE", "default_deny_sensitive_effects"),
    "kill_supervisor_unavailable": ("PARTIAL_ENFORCEMENT", "freeze_refuse_high_risk_execution"),
    "deviation_writer_unavailable": ("DEGRADED", "stop_high_risk_testing"),
    "gn_integrity_uncertain": ("CONTROL_INTEGRITY_FAILURE", "freeze_or_terminate_protected_workload"),
    "telemetry_untrusted": ("UNTRUSTED_TELEMETRY", "default_deny_sensitive_effects"),
}


@dataclass(frozen=True, slots=True)
class HealthReport:
    state: str
    capability_reduction: str
    detail: str

    def __post_init__(self) -> None:
        if self.state not in HEALTH_STATES:
            raise ValueError(f"unknown health state {self.state!r}")

    @property
    def safe_for_high_risk(self) -> bool:
        """Only HEALTHY/DEGRADED with deterministic policy is safe for high risk."""
        return self.state in {"HEALTHY", "DEGRADED"}

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def evaluate_health(
    *,
    observer_health: dict[str, bool],
    policy_integrity_ok: bool,
    supervisor_healthy: bool,
    deviation_writer_available: bool = True,
    telemetry_trusted: bool = True,
    control_integrity_ok: bool = True,
) -> HealthReport:
    """Evaluate GN health from its component health, failing closed."""
    if not control_integrity_ok:
        state, reduction = DEGRADATION_MATRIX["gn_integrity_uncertain"]
        return HealthReport(state, reduction, "containment control integrity is uncertain")
    if not policy_integrity_ok:
        state, reduction = DEGRADATION_MATRIX["policy_integrity_uncertain"]
        return HealthReport(state, reduction, "policy bundle integrity check failed")
    if not telemetry_trusted:
        state, reduction = DEGRADATION_MATRIX["telemetry_untrusted"]
        return HealthReport(state, reduction, "telemetry cannot be trusted")
    missing = tuple(kind for kind, ok in observer_health.items() if not ok)
    if missing:
        key = f"{missing[0]}_observer_unavailable"
        state, reduction = DEGRADATION_MATRIX.get(
            key, ("PARTIAL_OBSERVATION", "restrict_effects")
        )
        return HealthReport(state, reduction, "observer unavailable: " + ",".join(missing))
    if not supervisor_healthy:
        state, reduction = DEGRADATION_MATRIX["kill_supervisor_unavailable"]
        return HealthReport(state, reduction, "deterministic enforcement supervisor is unavailable")
    if not deviation_writer_available:
        state, reduction = DEGRADATION_MATRIX["deviation_writer_unavailable"]
        return HealthReport(state, reduction, "deviation evidence writer is unavailable")
    return HealthReport("HEALTHY", "none", "all containment components healthy")