"""Deterministic, side-effect-free controls admitted from the build-source capability pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ControlResult:
    skill_id: str
    decision: str
    reasons: tuple[str, ...]
    outputs: Mapping[str, object]
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


DELEGATED_HANDLERS = {
    "skill-navigator": "runtime/skill_navigator.py",
    "execution-contract-enforcer": "runtime/execution_contract.py",
    "outcome-verifier": "runtime/outcome_verifier.py",
    "skill-admission-controller": "runtime/admission_controller.py",
    "evidence-assembler": "runtime/evidence_assembler.py",
    "recovery-coordinator": "runtime/recovery.py",
    "context-compactor": "runtime/startup.py",
    "isolate-project-streams": "runtime/project_stream_controls.py",
    "govern-memory-fabric": "runtime/memory_fabric.py",
    "forge-skills-from-knowledge": "runtime/knowledge_foundry.py",
    "analyze-engineering-intelligence": "runtime/engineering_intelligence.py",
    "validate-contract-boundaries": "runtime/foundation_assurance.py",
    "evaluate-retrieval-readiness": "runtime/foundation_assurance.py",
    "gate-model-data-lifecycle": "runtime/foundation_assurance.py",
}

SKILL_FAMILIES = {
    "skill-bundle-resolver": "bundle",
    "human-handoff-state-transfer": "progress",
    "behavior-to-code-mapper": "impact",
    "dependency-impact-tracer": "impact",
    "memory-applicability-critic": "memory",
    "experience-reconstructor": "memory",
    "memory-injection-firewall": "memory",
    "candidate-memory-promoter": "memory",
    "procedural-memory-compiler": "compile",
    "active-evaluation-selector": "evaluation",
    "trajectory-failure-sentinel": "loop",
    "reasoning-utility-controller": "loop",
    "long-horizon-progress-ledger": "progress",
    "scenario-audit-generator": "evaluation",
    "dynamic-skill-detonator": "supply_chain",
    "permission-diff-auditor": "supply_chain",
    "provenance-signature-verifier": "supply_chain",
    "tool-loop-circuit-breaker": "loop",
    "paper-mechanism-extractor": "research",
    "productization-gap-analyzer": "research",
    "research-to-operation-translator": "research",
    "benchmark-domain-adapter": "research",
    "cross-paper-mechanism-fuser": "research",
    "read-only-speculation-controller": "topology",
    "bounded-workflow-topology-selector": "topology",
    "corpus-to-skill-tree-compiler": "compile",
    "trace-to-skill-compiler": "compile",
    "skill-coexecution-graph-builder": "impact",
    "evaluation-budget-allocator": "evaluation",
}

ALL_OPERATIONAL_SKILLS = tuple(sorted((*DELEGATED_HANDLERS, *SKILL_FAMILIES)))


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _tuple(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


def evaluate_memory(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    item = str(payload.get("retrieved_item", payload.get("memory", "")))
    original_goal = str(payload.get("original_goal", ""))
    requested = set(map(str, payload.get("requested_effects", ())))
    allowed = set(map(str, payload.get("allowed_effects", ())))
    provenance = str(payload.get("provenance", "unknown"))
    instruction_markers = (
        "ignore previous",
        "override policy",
        "reveal secret",
        "expand permission",
        "system message",
    )
    findings: list[str] = []
    if any(marker in item.casefold() for marker in instruction_markers):
        findings.append("embedded_instruction")
    if requested - allowed:
        findings.append("permission_expansion")
    if not provenance or provenance == "unknown":
        findings.append("unresolved_provenance")
    if (
        original_goal
        and item
        and not set(original_goal.casefold().split()) & set(item.casefold().split())
    ):
        findings.append("intent_divergence")

    current = dict(payload.get("current_variables", {}))
    prior = dict(payload.get("memory_variables", {}))
    mismatches = tuple(
        sorted(
            key
            for key in set(current) | set(prior)
            if current.get(key) != prior.get(key)
        )
    )
    if mismatches:
        findings.append("material_context_mismatch")

    promotion_checks = {
        "current_evidence": payload.get("evidence_status") == "current",
        "postconditions": payload.get("postconditions_passed") is True,
        "approved_scope": bool(payload.get("approved_scope")),
        "no_contradiction": not payload.get("contradictions"),
    }
    if skill_id in {"candidate-memory-promoter", "procedural-memory-compiler"}:
        decision = (
            "promote"
            if all(promotion_checks.values()) and not findings
            else "candidate_only"
        )
    elif findings:
        decision = "quarantine"
    else:
        decision = "allow_principles_only"
    return ControlResult(
        skill_id,
        decision,
        tuple(sorted(findings)),
        {
            "mismatches": mismatches,
            "promotion_checks": promotion_checks,
            "prohibited_replay": bool(mismatches or findings),
        },
        _tuple(payload.get("evidence", ())),
    )


def _policy_payload(skill_id: str, payload: object) -> dict:
    from .numeric_inputs import bounded_mapping, bounded_text

    bounded_text(skill_id, "policy skill identity", maximum=128, strip=False)
    return dict(bounded_mapping(payload, "policy payload", maximum=64))


def _policy_texts(value: object, name: str, *, maximum: int = 256, unique: bool = True) -> tuple[str, ...]:
    from .numeric_inputs import bounded_sequence, bounded_text

    values = bounded_sequence(value, name, maximum=maximum)
    result = tuple(bounded_text(item, name, maximum=256, strip=False) for item in values)
    if unique and len(set(result)) != len(result):
        raise ValueError(name + " identities must be unique")
    return result


def _policy_records(value: object, name: str, *, maximum: int = 1024) -> list[dict]:
    from .numeric_inputs import bounded_mapping, bounded_sequence, bounded_text

    values = bounded_sequence(value, name, maximum=maximum)
    result = []
    identities = set()
    for item in values:
        record = dict(bounded_mapping(item, name + " record", maximum=64))
        identity = bounded_text(record.get("id"), name + " identity", maximum=128, strip=False)
        if identity in identities:
            raise ValueError(name + " identities must be unique")
        identities.add(identity)
        result.append(record)
    return result


def _policy_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(name + " must be an actual boolean")
    return value


def _policy_number(value: object, name: str) -> float:
    from .numeric_inputs import finite_number

    return finite_number(value, name, minimum=0, maximum=1e12)


def resolve_bundle(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    from .numeric_inputs import bounded_integer

    payload = _policy_payload(skill_id, payload)
    requirements = set(_policy_texts(payload.get("requirements", ()), "bundle requirements"))
    candidates = _policy_records(payload.get("candidates", ()), "bundle candidates")
    for item in candidates:
        item["provides"] = _policy_texts(item.get("provides", ()), "candidate provides")
        item["conflicts"] = _policy_texts(item.get("conflicts", ()), "candidate conflicts")
        if item["id"] in item["conflicts"]:
            raise ValueError("bundle candidate cannot conflict with itself")
        item["cost"] = _policy_number(item.get("cost", 1), "candidate cost")
        item["risk"] = _policy_number(item.get("risk", 1), "candidate risk")
    limit = bounded_integer(payload.get("max_assets", 8), "maximum bundle assets", maximum=8)
    selected: list[dict[str, object]] = []
    unresolved = set(requirements)
    conflicts: set[str] = set()
    while unresolved and len(selected) < limit:
        eligible = []
        selected_ids = {str(item["id"]) for item in selected}
        selected_conflicts = {conflict for item in selected for conflict in item["conflicts"]}
        for item in candidates:
            item_id = str(item.get("id", ""))
            if not item_id or item_id in selected_ids:
                continue
            item_conflicts = set(map(str, item.get("conflicts", ())))
            if item_conflicts & selected_ids or item_id in selected_conflicts:
                conflicts.add(item_id)
                continue
            coverage = unresolved & set(map(str, item.get("provides", ())))
            if coverage:
                score = (
                    len(coverage) * 100
                    - float(item.get("cost", 1)) * 5
                    - float(item.get("risk", 1))
                )
                eligible.append((score, item_id, item, coverage))
        if not eligible:
            break
        _, _, winner, coverage = max(eligible, key=lambda entry: (entry[0], entry[1]))
        selected.append(winner)
        unresolved -= coverage
    decision = "resolved" if not unresolved else "incomplete"
    return ControlResult(
        skill_id,
        decision,
        (() if decision == "resolved" else ("requirements_unresolved",)),
        {
            "selected": tuple(str(item["id"]) for item in selected),
            "unresolved": tuple(sorted(unresolved)),
            "excluded_conflicts": tuple(sorted(conflicts)),
            "selection_hash": _stable([item.get("id") for item in selected]),
        },
    )


def assess_supply_chain(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    declared_permissions = set(map(str, payload.get("declared_permissions", ())))
    prior_permissions = set(map(str, payload.get("prior_permissions", ())))
    observed_effects = set(map(str, payload.get("observed_effects", ())))
    declared_effects = set(map(str, payload.get("declared_effects", ())))
    additions = declared_permissions - prior_permissions
    undeclared = observed_effects - declared_effects
    checks = {
        "hash_matches": payload.get("hash_matches") is True,
        "signature_valid": payload.get("signature_valid") is True,
        "owner_resolved": bool(payload.get("owner")),
        "build_chain_resolved": bool(payload.get("build_chain")),
    }
    reasons = []
    if additions:
        reasons.append("permission_expansion")
    if undeclared:
        reasons.append("observed_undeclared_effect")
    if not all(checks.values()):
        reasons.append("provenance_or_signature_failure")
    if skill_id == "dynamic-skill-detonator" and not payload.get("sandbox_adapter"):
        reasons.append("sandbox_adapter_missing")
    decision = (
        "admit"
        if not reasons
        else (
            "sandbox_required"
            if reasons == ["sandbox_adapter_missing"]
            else "quarantine"
        )
    )
    return ControlResult(
        skill_id,
        decision,
        tuple(reasons),
        {
            "permission_additions": tuple(sorted(additions)),
            "undeclared_effects": tuple(sorted(undeclared)),
            "verification_checks": checks,
            "synthetic_secrets_only": skill_id == "dynamic-skill-detonator",
        },
    )


def assess_loop(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    from .numeric_inputs import bounded_integer, bounded_sequence

    payload = _policy_payload(skill_id, payload)
    states = _policy_texts(payload.get("state_fingerprints", ()), "state fingerprints", maximum=4096, unique=False)
    evidence_counts = tuple(bounded_integer(value, "evidence count", minimum=0, maximum=1000000000)
                            for value in bounded_sequence(payload.get("evidence_counts", ()), "evidence counts", maximum=4096))
    repeated = len(states) != len(set(states))
    no_progress = len(evidence_counts) > 1 and evidence_counts[-1] <= evidence_counts[0]
    failures = bounded_integer(payload.get("failure_count", 0), "failure count", minimum=0, maximum=1000000000)
    failure_limit = bounded_integer(payload.get("failure_limit", 2), "failure limit", minimum=0, maximum=1000000000)
    cost = _policy_number(payload.get("next_step_cost", 0.0), "next step cost")
    gain = _policy_number(payload.get("expected_information_gain", 0.0), "expected information gain")
    risk = _policy_number(payload.get("trajectory_risk", 0.0), "trajectory risk")
    risk_limit = _policy_number(payload.get("risk_limit", 0.8), "risk limit")
    reasons = []
    if repeated:
        reasons.append("repeated_state")
    if no_progress:
        reasons.append("no_evidence_progress")
    if failures >= failure_limit:
        reasons.append("failure_budget_exhausted")
    if risk >= risk_limit:
        reasons.append("trajectory_risk_high")
    if gain <= cost:
        reasons.append("marginal_utility_nonpositive")
    decision = (
        "continue"
        if not reasons
        else ("escalate" if "trajectory_risk_high" in reasons else "stop")
    )
    return ControlResult(
        skill_id,
        decision,
        tuple(reasons),
        {
            "expected_gain": gain,
            "next_step_cost": cost,
            "trajectory_risk": risk,
            "remaining_failure_budget": max(
                0, failure_limit - failures
            ),
        },
    )


def trace_impact(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    changed = set(map(str, payload.get("changed", ())))
    edges = [(str(item[0]), str(item[1])) for item in payload.get("edges", ())]
    impacted = set(changed)
    frontier = list(changed)
    while frontier:
        source = frontier.pop(0)
        for left, right in sorted(edges):
            if left == source and right not in impacted:
                impacted.add(right)
                frontier.append(right)
    observations = [dict(item) for item in payload.get("observations", ())]
    mapped = tuple(
        sorted(
            (str(item.get("behavior", "")), str(item.get("owner", "unresolved")))
            for item in observations
        )
    )
    unresolved = tuple(behavior for behavior, owner in mapped if owner == "unresolved")
    return ControlResult(
        skill_id,
        "mapped" if not unresolved else "review_required",
        (() if not unresolved else ("unresolved_behavior_owner",)),
        {
            "impacted": tuple(sorted(impacted - changed)),
            "behavior_owners": mapped,
            "unresolved": unresolved,
        },
    )


def select_evaluation(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    cases = [dict(item) for item in payload.get("cases", ())]
    budget = max(0, int(payload.get("budget", len(cases))))
    ranked = []
    for item in cases:
        score = (
            float(item.get("risk", 0)) * 4
            + float(item.get("novelty", 0)) * 3
            + float(item.get("disagreement", 0)) * 3
            + float(item.get("impact", 0)) * 2
            - float(item.get("evidence_quality", 0))
        )
        ranked.append((score, str(item.get("id", "")), item))
    selected = tuple(
        item_id
        for _, item_id, _ in sorted(ranked, key=lambda entry: (-entry[0], entry[1]))[
            :budget
        ]
    )
    scenarios = tuple(
        sorted({str(item.get("risk_class", "general")) for _, _, item in ranked})
    )
    return ControlResult(
        skill_id,
        "allocated",
        (),
        {
            "selected_cases": selected,
            "scenario_classes": scenarios,
            "human_review_required": tuple(
                item_id for score, item_id, _ in ranked if score >= 6
            ),
        },
    )


def process_research(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    required = set(
        map(
            str,
            payload.get(
                "required_fields",
                ("mechanism", "assumptions", "evidence", "limitations"),
            ),
        )
    )
    record = dict(payload.get("record", {}))
    missing = tuple(sorted(field for field in required if not record.get(field)))
    available = set(map(str, payload.get("available_controls", ())))
    required_controls = set(map(str, payload.get("required_controls", ())))
    gaps = tuple(sorted(required_controls - available))
    conflicts = tuple(sorted(map(str, payload.get("conflicts", ()))))
    reasons = tuple(
        name
        for name, active in (
            ("missing_research_fields", bool(missing)),
            ("productization_gaps", bool(gaps)),
            ("mechanism_conflicts", bool(conflicts)),
        )
        if active
    )
    decision = "candidate" if not reasons else "research_incomplete"
    return ControlResult(
        skill_id,
        decision,
        reasons,
        {
            "missing_fields": missing,
            "control_gaps": gaps,
            "conflicts": conflicts,
            "promotion_state": "candidate_only",
            "record_hash": _stable(record),
        },
        _tuple(payload.get("evidence", ())),
    )


def track_progress(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    from .numeric_inputs import bounded_text

    payload = _policy_payload(skill_id, payload)
    milestones = _policy_records(payload.get("milestones", ()), "milestones", maximum=4096)
    for item in milestones:
        item["postcondition"] = _policy_bool(item.get("postcondition", False), "milestone postcondition")
        item["blocked"] = _policy_bool(item.get("blocked", False), "milestone blocked")
        item["evidence"] = _policy_texts(item.get("evidence", ()), "milestone evidence")
    goal = payload.get("goal", "")
    if type(goal) is not str:
        raise ValueError("handoff goal must be actual text")
    if goal:
        bounded_text(goal, "handoff goal", maximum=4096, strip=False)
    for field in ("constraints", "decisions", "evidence", "next_actions"):
        payload[field] = _policy_texts(payload.get(field, ()), "handoff " + field)
    states = []
    for item in milestones:
        if item.get("postcondition") is True and item.get("evidence"):
            state = "complete"
        elif item.get("blocked"):
            state = "blocked"
        else:
            state = "partial"
        states.append((str(item.get("id", "")), state))
    unresolved = tuple(item_id for item_id, state in states if state != "complete")
    handoff_required = ("goal", "constraints", "decisions", "evidence", "next_actions")
    missing_handoff = tuple(
        field for field in handoff_required if not payload.get(field)
    )
    decision = "complete" if states and not unresolved and not missing_handoff else "resumable"
    return ControlResult(
        skill_id,
        decision,
        (() if not missing_handoff else ("handoff_fields_missing",)),
        {
            "milestones": tuple(states),
            "unresolved": unresolved,
            "missing_handoff_fields": missing_handoff,
        },
    )


def compile_candidate(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    payload = _policy_payload(skill_id, payload)
    records = _policy_records(payload.get("records", ()), "compilation records", maximum=4096)
    for item in records:
        item["verified"] = _policy_bool(item.get("verified", False), "record verified")
        item["evidence"] = _policy_texts(item.get("evidence", ()), "record evidence")
    accepted = tuple(
        sorted(
            str(item.get("id"))
            for item in records
            if item.get("verified") is True and item.get("evidence")
        )
    )
    rejected = tuple(
        sorted(
            str(item.get("id"))
            for item in records
            if str(item.get("id")) not in accepted
        )
    )
    return ControlResult(
        skill_id,
        "candidate_compiled" if accepted else "insufficient_evidence",
        (() if accepted else ("no_verified_records",)),
        {
            "accepted_records": accepted,
            "rejected_records": rejected,
            "activation": "candidate",
            "compilation_hash": _stable(accepted),
        },
    )


def select_topology(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    payload = _policy_payload(skill_id, payload)
    approved = _policy_records(payload.get("approved_templates", ()), "approved templates")
    risk = _policy_number(payload.get("risk", 0), "topology risk")
    complexity = _policy_number(payload.get("complexity", 0), "topology complexity")
    for item in approved:
        item["max_risk"] = _policy_number(item.get("max_risk", 1), "template maximum risk")
        item["max_complexity"] = _policy_number(item.get("max_complexity", 1), "template maximum complexity")
        item["cost"] = _policy_number(item.get("cost", 0), "template cost")
    if skill_id == "read-only-speculation-controller":
        read_only = _policy_bool(payload.get("read_only", False), "read-only speculation")
    eligible = [
        item
        for item in approved
        if float(item.get("max_risk", 1)) >= risk
        and float(item.get("max_complexity", 1)) >= complexity
    ]
    eligible.sort(
        key=lambda item: (float(item.get("cost", 0)), str(item.get("id", "")))
    )
    selected = str(eligible[0].get("id")) if eligible else None
    if skill_id == "read-only-speculation-controller":
        return ControlResult(
            skill_id,
            "proposal_only" if read_only else "denied",
            (() if read_only else ("non_read_speculation_forbidden",)),
            {
                "selected_template": selected,
                "cache_state": "quarantined",
                "executed": False,
            },
        )
    return ControlResult(
        skill_id,
        "selected" if selected else "no_approved_topology",
        (() if selected else ("approved_template_missing",)),
        {"selected_template": selected},
    )


def run_control(skill_id: str, payload: Mapping[str, object]) -> ControlResult:
    if skill_id in DELEGATED_HANDLERS:
        return ControlResult(
            skill_id,
            "delegate",
            (),
            {"handler": DELEGATED_HANDLERS[skill_id], "payload_hash": _stable(payload)},
        )
    family = SKILL_FAMILIES.get(skill_id)
    if family == "memory":
        return evaluate_memory(skill_id, payload)
    if family == "bundle":
        return resolve_bundle(skill_id, payload)
    if family == "supply_chain":
        return assess_supply_chain(skill_id, payload)
    if family == "loop":
        return assess_loop(skill_id, payload)
    if family == "impact":
        return trace_impact(skill_id, payload)
    if family == "evaluation":
        return select_evaluation(skill_id, payload)
    if family == "research":
        return process_research(skill_id, payload)
    if family == "progress":
        return track_progress(skill_id, payload)
    if family == "compile":
        return compile_candidate(skill_id, payload)
    if family == "topology":
        return select_topology(skill_id, payload)
    raise KeyError(f"unknown operational skill: {skill_id}")
