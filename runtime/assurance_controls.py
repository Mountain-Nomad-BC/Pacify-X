"""Deterministic controls for evidence-first commissioning, containment, and assurance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class AssuranceResult:
    control_id: str
    decision: str
    reasons: tuple[str, ...]
    outputs: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


ASSURANCE_CONTROLS = (
    "audit-ai-runtime-assurance",
    "certify-skeptical-engineering",
    "commission-evidence-first-project",
    "discover-environment-safely",
    "propose-change-intelligence",
    "quarantine-external-tools",
    "supervise-contained-execution",
)

MUTATING_EFFECTS = {
    "write_workspace", "write_global", "install_project", "install_global", "network",
    "service_start", "migration", "remote_git", "mcp_connect", "auth_change",
    "destructive", "load_test", "chaos_test", "red_team",
}
APPROVED_CREDENTIAL_STORES = {
    "git-credential-manager", "windows-credential-manager", "keychain",
    "secret-service", "encrypted-secret-store", "ephemeral-environment-injection",
}


def _stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _strings(values: object) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values or ()}))


def discover_environment(payload: Mapping[str, object]) -> AssuranceResult:
    observed = {str(key): dict(value) for key, value in dict(payload.get("observed_tools", {})).items()}
    required = set(map(str, payload.get("required_tools", ())))
    missing = tuple(sorted(name for name in required if not observed.get(name, {}).get("available")))
    proposals = [dict(item) for item in payload.get("proposed_changes", ())]
    approval_required = tuple(sorted(str(item.get("id", "unnamed")) for item in proposals if str(item.get("effect")) in MUTATING_EFFECTS))
    credential_store = str(payload.get("credential_store", ""))
    credential_warning = None
    if credential_store and credential_store not in APPROVED_CREDENTIAL_STORES:
        credential_warning = "credential_store_not_approved"
    todo_records = tuple(sorted(str(item) for item in payload.get("todo_stub_findings", ())))
    decision = "approval_required" if approval_required else "report_only"
    reasons = tuple(name for name, active in (
        ("required_tools_missing", bool(missing)),
        ("mutating_setup_requires_approval", bool(approval_required)),
        ("credential_store_not_approved", credential_warning is not None),
    ) if active)
    return AssuranceResult("discover-environment-safely", decision, reasons, {
        "observed_tools": tuple(sorted((name, bool(item.get("available")), str(item.get("version", "unknown"))) for name, item in observed.items())),
        "missing_required_tools": missing,
        "approval_required_for": approval_required,
        "todo_stub_findings": todo_records,
        "credential_guidance": "use_os_or_ephemeral_secret_store" if credential_warning else "approved_or_not_requested",
        "executed_changes": False,
        "inventory_hash": _stable(observed),
    })


def commission_project(payload: Mapping[str, object]) -> AssuranceResult:
    required = ("goal", "users", "data", "accessibility", "security", "integrations", "operations", "acceptance")
    answers = dict(payload.get("answers", {}))
    missing = tuple(field for field in required if not answers.get(field))
    facts = [dict(item) for item in payload.get("facts", ())]
    invalid_facts = tuple(sorted(str(item.get("id", "unnamed")) for item in facts if not item.get("evidence")))
    assumptions = [dict(item) for item in payload.get("assumptions", ())]
    unknowns = [dict(item) for item in payload.get("unknowns", ())]
    high_risk = tuple(sorted(
        str(item.get("id", "unnamed")) for item in (*assumptions, *unknowns)
        if str(item.get("risk", "low")) in {"high", "critical"} and not item.get("approved")
    ))
    reasons = tuple(name for name, active in (
        ("commissioning_sections_missing", bool(missing)),
        ("facts_without_evidence", bool(invalid_facts)),
        ("high_risk_unknowns_unresolved", bool(high_risk)),
    ) if active)
    ledger = tuple(sorted(
        (str(item.get("id", "unnamed")), str(item.get("confidence", "unknown")), bool(item.get("confirmed")), str(item.get("risk", "low")))
        for item in assumptions
    ))
    return AssuranceResult("commission-evidence-first-project", "review_ready" if not reasons else "blocked", reasons, {
        "missing_sections": missing,
        "invalid_fact_ids": invalid_facts,
        "unresolved_high_risk_ids": high_risk,
        "assumption_ledger": ledger,
        "legal_compliance_claim": False,
        "implementation_authorized": not high_risk and not missing and bool(payload.get("human_acceptance")),
        "brief_hash": _stable({"answers": answers, "facts": facts, "assumptions": assumptions, "unknowns": unknowns}),
    })


def _path_within(path: str, roots: Sequence[str]) -> bool:
    candidate = PurePosixPath(path.replace("\\", "/"))
    for root in roots:
        allowed = PurePosixPath(str(root).replace("\\", "/"))
        if candidate == allowed or allowed in candidate.parents:
            return True
    return False


def supervise_action(payload: Mapping[str, object]) -> AssuranceResult:
    effects = set(map(str, payload.get("effects", ())))
    allowed_effects = set(map(str, payload.get("allowed_effects", ())))
    paths = tuple(map(str, payload.get("target_paths", ())))
    owned = tuple(map(str, payload.get("owned_paths", ())))
    budgets = dict(payload.get("budget", {}))
    limits = dict(payload.get("limits", {}))
    reasons: list[str] = []
    undeclared = tuple(sorted(effects - allowed_effects))
    if undeclared:
        reasons.append("effect_not_allowed")
    outside = tuple(sorted(path for path in paths if not _path_within(path, owned))) if paths else ()
    if outside:
        reasons.append("target_outside_owned_scope")
    exceeded = tuple(sorted(key for key, value in budgets.items() if key in limits and float(value) > float(limits[key])))
    if exceeded:
        reasons.append("budget_exceeded")
    approval_needed = bool(effects & MUTATING_EFFECTS)
    if approval_needed and payload.get("approval") is not True:
        reasons.append("approval_missing")
    if payload.get("policy_override_requested"):
        reasons.append("policy_override_forbidden")
    decision = "allow" if not reasons else ("escalate" if reasons == ["approval_missing"] else "block")
    return AssuranceResult("supervise-contained-execution", decision, tuple(reasons), {
        "undeclared_effects": undeclared,
        "outside_scope": outside,
        "exceeded_budgets": exceeded,
        "approval_required": approval_needed,
        "audit_record_hash": _stable(payload),
    })


def quarantine_tool(payload: Mapping[str, object]) -> AssuranceResult:
    required = ("source", "sha256", "license", "permissions", "vulnerabilities", "policy_compatible")
    missing = tuple(field for field in required if payload.get(field) in (None, "", ()))
    vulnerabilities = tuple(str(item) for item in payload.get("vulnerabilities", ()))
    malicious = tuple(str(item) for item in payload.get("malicious_indicators", ()))
    reasons: list[str] = []
    if missing:
        reasons.append("static_evidence_missing")
    if vulnerabilities:
        reasons.append("known_vulnerabilities")
    if malicious:
        reasons.append("malicious_indicators")
    if payload.get("policy_compatible") is not True:
        reasons.append("policy_incompatible_or_unknown")
    dynamic_requested = bool(payload.get("dynamic_analysis_requested"))
    if dynamic_requested and not (
        payload.get("sandbox_approved") is True
        and payload.get("synthetic_secrets_only") is True
        and payload.get("network_policy_declared") is True
    ):
        reasons.append("dynamic_analysis_not_contained")
    if payload.get("approval") is not True:
        reasons.append("explicit_approval_missing")
    decision = "admit" if not reasons else "quarantine"
    return AssuranceResult("quarantine-external-tools", decision, tuple(reasons), {
        "execution": "allowed_after_admission" if decision == "admit" else "blocked",
        "integration": "allowed_after_admission" if decision == "admit" else "blocked",
        "missing_static_fields": missing,
        "vulnerability_count": len(vulnerabilities),
        "malicious_indicator_count": len(malicious),
        "dynamic_phase_separately_approved": dynamic_requested and "dynamic_analysis_not_contained" not in reasons,
        "intake_hash": _stable(payload),
    })


LEVEL_REQUIREMENTS = {
    0: {"inventory"},
    1: {"inventory", "baseline"},
    2: {"inventory", "baseline", "functional"},
    3: {"inventory", "baseline", "functional", "security", "dependency"},
    4: {"inventory", "baseline", "functional", "security", "dependency", "user_workflows", "authorization"},
    5: {"inventory", "baseline", "functional", "security", "dependency", "user_workflows", "authorization", "resilience", "scaling"},
    6: {"inventory", "baseline", "functional", "security", "dependency", "user_workflows", "authorization", "resilience", "scaling", "chaos", "adversarial_repairs"},
    7: {"inventory", "baseline", "functional", "security", "dependency", "user_workflows", "authorization", "resilience", "scaling", "chaos", "adversarial_repairs", "documentation", "operations"},
}


def certify_skeptically(payload: Mapping[str, object]) -> AssuranceResult:
    level = int(payload.get("level", -1))
    if level not in LEVEL_REQUIREMENTS:
        return AssuranceResult("certify-skeptical-engineering", "invalid", ("invalid_maturity_level",), {"level": level})
    evidence = set(map(str, payload.get("current_evidence_classes", ())))
    missing = tuple(sorted(LEVEL_REQUIREMENTS[level] - evidence))
    denominator = int(payload.get("discovery_denominator", 0))
    covered = int(payload.get("covered_items", 0))
    unknowns = _strings(payload.get("unknowns", ()))
    contradictions = _strings(payload.get("contradictions", ()))
    superseded = payload.get("evidence_revision") != payload.get("discovery_revision")
    reasons = tuple(name for name, active in (
        ("required_evidence_missing", bool(missing)),
        ("coverage_denominator_incomplete", denominator <= 0 or covered != denominator),
        ("unknowns_unclassified", bool(unknowns)),
        ("contradictions_unresolved", bool(contradictions)),
        ("evidence_superseded_by_discovery", superseded),
    ) if active)
    return AssuranceResult("certify-skeptical-engineering", "certified" if not reasons else "not_certified", reasons, {
        "level": level,
        "missing_evidence_classes": missing,
        "coverage": (covered, denominator),
        "unknowns": unknowns,
        "contradictions": contradictions,
        "superseded": superseded,
        "claim": "current evidence survived approved invalidation attempts" if not reasons else "certification incomplete",
    })


def audit_runtime(payload: Mapping[str, object]) -> AssuranceResult:
    if payload.get("opt_in") is not True:
        return AssuranceResult("audit-ai-runtime-assurance", "disabled", ("explicit_opt_in_required",), {"collected": False})
    telemetry = dict(payload.get("telemetry", {}))
    prohibited = tuple(sorted(key for key in telemetry if key.casefold() in {"raw_prompt", "raw_response", "secret", "token", "credential"}))
    required = ("runtime_id", "model_version", "evidence_coverage", "latency_ms", "drift", "benchmark")
    missing = tuple(field for field in required if telemetry.get(field) in (None, ""))
    retention = int(payload.get("retention_days", 0))
    reasons = tuple(name for name, active in (
        ("prohibited_telemetry_present", bool(prohibited)),
        ("required_telemetry_missing", bool(missing)),
        ("retention_out_of_policy", retention < 0 or retention > int(payload.get("max_retention_days", 30))),
        ("benchmark_not_passed", telemetry.get("benchmark") != "passed"),
        ("drift_detected", telemetry.get("drift") not in {"none", "within_threshold"}),
    ) if active)
    safe_telemetry = {key: value for key, value in telemetry.items() if key not in prohibited}
    passport = {
        "runtime_id": safe_telemetry.get("runtime_id", "unknown"),
        "model_version": safe_telemetry.get("model_version", "unknown"),
        "evidence_coverage": safe_telemetry.get("evidence_coverage", 0),
        "benchmark": safe_telemetry.get("benchmark", "unknown"),
        "drift": safe_telemetry.get("drift", "unknown"),
        "health": "certified" if not reasons else "degraded",
    }
    return AssuranceResult("audit-ai-runtime-assurance", "certified" if not reasons else "degraded", reasons, {
        "collected": True,
        "passport": passport,
        "redacted_trace_hash": _stable(safe_telemetry),
        "prohibited_fields": prohibited,
        "missing_fields": missing,
        "network_collection": False,
    })


def propose_change_intelligence(payload: Mapping[str, object]) -> AssuranceResult:
    required = ("capability", "baseline", "validation_dataset", "false_positive_controls", "safety_effects")
    missing = tuple(field for field in required if not payload.get(field))
    return AssuranceResult("propose-change-intelligence", "candidate" if not missing else "incomplete", (() if not missing else ("candidate_contract_incomplete",)), {
        "missing_fields": missing,
        "activation": "proposal_only",
        "auto_activate": False,
        "candidate_hash": _stable(payload),
        "supported_clusters": ("change-impact", "semantic-drift", "architecture-entropy", "rule-collision", "living-documentation"),
    })


def run_assurance_control(control_id: str, payload: Mapping[str, object]) -> AssuranceResult:
    handlers = {
        "discover-environment-safely": discover_environment,
        "commission-evidence-first-project": commission_project,
        "supervise-contained-execution": supervise_action,
        "quarantine-external-tools": quarantine_tool,
        "certify-skeptical-engineering": certify_skeptically,
        "audit-ai-runtime-assurance": audit_runtime,
        "propose-change-intelligence": propose_change_intelligence,
    }
    try:
        return handlers[control_id](payload)
    except KeyError as error:
        raise KeyError(f"unknown assurance control: {control_id}") from error
