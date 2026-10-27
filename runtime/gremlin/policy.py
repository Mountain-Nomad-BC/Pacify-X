"""Gremlin policy profiles and policy bundle resolution.

Policy is *containment policy*, not a general policy engine. It is deliberately
small and deterministic: it decides whether an observed effect is authorized and
what remediation/enforcement applies. The policy bundle carries an integrity
digest so policy tampering is detectable (GN-INV-002, GN-INV-008).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Mapping

from ..json_io import bounded_canonical_json_bytes

SCHEMA_VERSION = "px.gremlin-policy/1.0"

# Policy profiles (plan section 36). ``gn-observe-only`` is explicitly NOT real
# containment and never counts as containment proof.
POLICY_PROFILES = (
    "gn-redteam-strict",
    "gn-agent-sandbox",
    "gn-development",
    "gn-integration-test",
    "gn-network-denied",
    "gn-network-synthetic",
    "gn-high-risk-autonomy",
    "projection-reconciliation",
    "gn-observe-only",
)

OBSERVE_ONLY = "gn-observe-only"


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    description: str
    effect_type: str
    allow_if_capability_lease_valid: bool
    remediation_attempts: int
    remediation_action: str
    remediation_timeout_ms: int
    failure_action: str
    severity: str
    create_deviation: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id.startswith("GN-"):
            raise ValueError("policy rule id must be a GN-* identity")
        if self.remediation_attempts not in (0, 1):
            raise ValueError("remediation attempts must be 0 (critical) or 1 (one-shot)")
        if self.remediation_timeout_ms <= 0 or self.remediation_timeout_ms > 600_000:
            raise ValueError("remediation timeout must be bounded and positive")
        if self.failure_action not in {"terminate_execution_tree", "freeze_execution", "revoke_network", "deny"}:
            raise ValueError("unknown failure action")
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("unknown severity")


@dataclass(frozen=True, slots=True)
class PolicyProfile:
    name: str
    real_containment: bool
    default_failure_action: str
    fail_closed: bool
    rules: tuple[PolicyRule, ...]
    network_enforcement: bool = True
    filesystem_enforcement: bool = True
    process_tree_enforcement: bool = True

    def __post_init__(self) -> None:
        if self.name not in POLICY_PROFILES:
            raise ValueError(f"unknown policy profile {self.name!r}")
        if self.name == OBSERVE_ONLY and self.real_containment:
            raise ValueError("gn-observe-only must not be treated as real containment")
        if type(self.rules) is not tuple or any(type(rule) is not PolicyRule for rule in self.rules):
            raise ValueError("policy rules must be a typed tuple")

    def rule_for(self, effect_type: str) -> PolicyRule | None:
        for rule in self.rules:
            if rule.effect_type == effect_type:
                return rule
        return None


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    bundle_id: str
    revision: str
    profiles: tuple[PolicyProfile, ...]
    #: Integrity identity over the profile definitions; tampering is detectable.
    integrity_sha256: str = ""

    def __post_init__(self) -> None:
        if type(self.profiles) is not tuple or not self.profiles:
            raise ValueError("policy bundle requires at least one profile")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "bundle_id": self.bundle_id,
            "revision": self.revision,
            "profiles": [
                {**asdict(profile), "rules": [asdict(rule) for rule in profile.rules]}
                for profile in self.profiles
            ],
        }

    @property
    def computed_integrity_sha256(self) -> str:
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=1_048_576)).hexdigest()

    def integrity_ok(self) -> bool:
        return self.integrity_sha256 == "" or self.integrity_sha256 == self.computed_integrity_sha256

    def profile(self, name: str) -> PolicyProfile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"policy profile {name!r} is not in the bundle")


def default_policy_bundle() -> PolicyBundle:
    """The canonical default policy bundle.

    ``gn-redteam-strict`` denies unapproved outbound network with one bounded
    corrective attempt; ``GN-SELF-001`` gives containment-control interference
    zero attempts and immediate termination.
    """
    network_rule = PolicyRule(
        rule_id="GN-NET-001",
        description="Protected agents may not initiate unapproved outbound network connections.",
        effect_type="outbound_network",
        allow_if_capability_lease_valid=True,
        remediation_attempts=1,
        remediation_action="close_connection",
        remediation_timeout_ms=1500,
        failure_action="terminate_execution_tree",
        severity="high",
    )
    self_rule = PolicyRule(
        rule_id="GN-SELF-001",
        description="Protected workloads may not interfere with Gremlin Nanny.",
        effect_type="containment_control_interference",
        allow_if_capability_lease_valid=False,
        remediation_attempts=0,
        remediation_action="none",
        remediation_timeout_ms=1,
        failure_action="terminate_execution_tree",
        severity="critical",
    )
    fs_rule = PolicyRule(
        rule_id="GN-FS-001",
        description="Protected agents may not write outside approved roots.",
        effect_type="filesystem_escape",
        allow_if_capability_lease_valid=True,
        remediation_attempts=1,
        remediation_action="remove_created_file",
        remediation_timeout_ms=1500,
        failure_action="freeze_execution",
        severity="high",
    )
    strict = PolicyProfile(
        name="gn-redteam-strict",
        real_containment=True,
        default_failure_action="terminate_execution_tree",
        fail_closed=True,
        rules=(network_rule, self_rule, fs_rule),
    )

    def _supervised_rule(rule_id, effect_type, allow, action="freeze_execution", severity="medium"):
        return PolicyRule(
            rule_id=rule_id,
            description=f"Supervised reconciliation profile: {effect_type}.",
            effect_type=effect_type,
            allow_if_capability_lease_valid=allow,
            remediation_attempts=0,
            remediation_action="none",
            remediation_timeout_ms=1,
            failure_action=action,
            severity=severity,
        )

    # Supervised canonical-projection reconciliation: bounded, freeze-first.
    # Custody for the admitted artifacts comes from the governance ledger, so an
    # unauthorized effect freezes the worker instead of killing it mid-rebuild.
    projection_reconciliation = PolicyProfile(
        name="projection-reconciliation",
        real_containment=True,
        default_failure_action="freeze_execution",
        fail_closed=True,
        rules=(
            _supervised_rule("GN-PR-FS-001", "filesystem_write", allow=True),
            _supervised_rule("GN-PR-NET-001", "outbound_network", allow=False),
            _supervised_rule("GN-PR-PROC-001", "process_spawn", allow=False),
            _supervised_rule("GN-PR-SELF-001", "containment_control_interference", allow=False, severity="critical"),
        ),
        # Honest enforcement surface: the host truly observes the process tree
        # (Toolhelp32 snapshot of its own children). Filesystem effects are
        # custody-gated by the governance ledger instead of kernel observation,
        # and no network observation is claimed.
        network_enforcement=False,
        filesystem_enforcement=False,
        process_tree_enforcement=True,
    )
    observe_only = PolicyProfile(
        name=OBSERVE_ONLY,
        real_containment=False,
        default_failure_action="deny",
        fail_closed=False,
        rules=(),
        network_enforcement=False,
        filesystem_enforcement=False,
        process_tree_enforcement=False,
    )
    bundle = PolicyBundle(
        bundle_id="gn-default", revision="gn-default-r1",
        profiles=(strict, projection_reconciliation, observe_only),
    )
    return PolicyBundle(
        bundle_id=bundle.bundle_id,
        revision=bundle.revision,
        profiles=bundle.profiles,
        integrity_sha256=bundle.computed_integrity_sha256,
    )


def policy_bundle_from_dict(value: Mapping[str, Any]) -> PolicyBundle:
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("typed gremlin policy bundle required")
    profiles: list[PolicyProfile] = []
    for raw in value.get("profiles", []):
        rules = tuple(PolicyRule(**rule) for rule in raw.get("rules", []))
        payload = {key: item for key, item in raw.items() if key != "rules"}
        profiles.append(PolicyProfile(rules=rules, **payload))
    bundle = PolicyBundle(
        bundle_id=str(value["bundle_id"]),
        revision=str(value["revision"]),
        profiles=tuple(profiles),
        integrity_sha256=str(value.get("integrity_sha256", "")),
    )
    if not bundle.integrity_ok():
        raise ValueError("gremlin policy bundle integrity check failed")
    return bundle