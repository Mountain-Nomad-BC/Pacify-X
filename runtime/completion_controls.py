"""Deterministic controls recovered from the final REL-013 intake.

This module is an independent clean-room implementation.  It consolidates the
non-overlapping mechanisms from the late intake into existing Pacify-X control
planes instead of creating parallel schedulers, memories, resolvers, or agent
runtimes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable, Mapping, Sequence

from pathlib import Path
from .numeric_inputs import (
    bounded_integer,
    bounded_mapping,
    bounded_sequence,
    bounded_text,
    finite_number,
)


PIPELINE_STAGES = (
    "normalize_task",
    "query_hydration",
    "dependent_query_hydration",
    "candidate_discovery",
    "candidate_hydration",
    "hard_filtering",
    "independent_scoring",
    "package_selection",
    "post_selection_hydration",
    "post_selection_filtering",
    "evidence_feedback",
)
MEMBERSHIP_PRESERVING = {
    "query_hydration",
    "dependent_query_hydration",
    "candidate_hydration",
    "independent_scoring",
    "post_selection_hydration",
    "evidence_feedback",
}
MEMBERSHIP_CHANGING = {
    "candidate_discovery",
    "hard_filtering",
    "package_selection",
    "post_selection_filtering",
}
TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled", "timed_out"}


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_candidate_stage_trace(
    trace: Sequence[Mapping[str, object]],
    *,
    required_components: Iterable[str] = (),
) -> dict[str, object]:
    """Validate stage order, membership authority, and explicit failures."""
    errors: list[str] = []
    stages = tuple(str(item.get("stage", "")) for item in trace)
    if stages != PIPELINE_STAGES:
        errors.append("pipeline stages are missing, duplicated, or out of order")
    required = set(required_components)
    observed_components: set[str] = set()
    previous_ids: tuple[str, ...] | None = None
    removals: set[str] = set()
    for item in trace:
        stage = str(item.get("stage", ""))
        component = str(item.get("component", ""))
        if component:
            observed_components.add(component)
        status = str(item.get("status", ""))
        required_component = bool(item.get("required", component in required))
        if status not in {"ok", "abstained", "failed"}:
            errors.append(f"{stage}: component status is not explicit")
        if required_component and status != "ok":
            errors.append(f"{stage}: required component did not succeed")
        if not required_component and status == "failed":
            errors.append(f"{stage}: optional failure must be recorded as abstained")
        input_ids = tuple(str(value) for value in item.get("input_ids", ()))
        output_ids = tuple(str(value) for value in item.get("output_ids", ()))
        if len(output_ids) != len(set(output_ids)):
            errors.append(f"{stage}: duplicate candidate identity")
        if stage in MEMBERSHIP_PRESERVING and input_ids != output_ids:
            errors.append(f"{stage}: membership or order changed outside a filter")
        if previous_ids is not None and input_ids != previous_ids:
            errors.append(f"{stage}: input does not equal prior stage output")
        if stage in {"hard_filtering", "post_selection_filtering"}:
            removed = set(input_ids) - set(output_ids)
            reasons = item.get("removal_reasons", {})
            if not isinstance(reasons, Mapping) or removed - set(map(str, reasons)):
                errors.append(f"{stage}: removed candidate lacks a reason")
            removals.update(removed)
        previous_ids = output_ids
    missing_components = sorted(required - observed_components)
    if missing_components:
        errors.append("required components absent: " + ", ".join(missing_components))
    payload = {
        "valid": not errors,
        "stages": stages,
        "removed_candidates": tuple(sorted(removals)),
        "errors": tuple(errors),
    }
    return {**payload, "trace_sha256": stable_hash(payload)}


def verify_batch_independent_scores(
    baseline: Mapping[str, Mapping[str, float]],
    expanded: Mapping[str, Mapping[str, float]],
) -> dict[str, object]:
    """Prove that unrelated batch additions cannot change intrinsic scores."""
    changed = []
    for candidate_id, components in sorted(baseline.items()):
        if candidate_id not in expanded or dict(components) != dict(
            expanded[candidate_id]
        ):
            changed.append(candidate_id)
    payload = {"valid": not changed, "changed_candidate_ids": tuple(changed)}
    return {**payload, "evidence_sha256": stable_hash(payload)}


def optimize_candidate_package(
    candidates: Sequence[Mapping[str, object]],
    *,
    required_capabilities: Iterable[str] = (),
    required_kinds: Iterable[str] = (),
    max_cost: float,
    max_items: int = 15,
    family_floor: float = 0.35,
) -> dict[str, object]:
    """Select a dependency-closed package by deterministic marginal utility."""
    if max_cost < 0 or max_items < 1 or not 0 <= family_floor <= 1:
        raise ValueError("invalid package budget")
    records = {str(item["id"]): dict(item) for item in candidates}
    required_caps = set(map(str, required_capabilities))
    required_kind_set = set(map(str, required_kinds))
    selected: list[str] = []
    covered: set[str] = set()
    families: dict[str, int] = defaultdict(int)
    spent = 0.0
    rejected: dict[str, str] = {}

    def adjusted(item: Mapping[str, object]) -> tuple[float, str]:
        family = str(item.get("family", item.get("provider", "default")))
        attenuation = max(family_floor, 1.0 / (families[family] + 1))
        capabilities = set(map(str, item.get("capabilities", ())))
        marginal = len((required_caps - covered) & capabilities)
        score = float(item.get("intrinsic_score", 0.0)) * attenuation + 25 * marginal
        return score, str(item["id"])

    while len(selected) < max_items:
        eligible = []
        for item in records.values():
            candidate_id = str(item["id"])
            if candidate_id in selected or candidate_id in rejected:
                continue
            if item.get("admitted") is not True:
                rejected[candidate_id] = "not_admitted"
                continue
            cost = float(item.get("cost", 0.0))
            if spent + cost > max_cost:
                rejected[candidate_id] = "cost_budget"
                continue
            eligible.append(item)
        if not eligible:
            break
        item = min(eligible, key=lambda row: (-adjusted(row)[0], adjusted(row)[1]))
        candidate_id = str(item["id"])
        score, _ = adjusted(item)
        if score <= 0 and required_caps <= covered:
            rejected[candidate_id] = "no_marginal_utility"
            continue
        selected.append(candidate_id)
        spent += float(item.get("cost", 0.0))
        covered.update(map(str, item.get("capabilities", ())))
        families[str(item.get("family", item.get("provider", "default")))] += 1
        if required_caps <= covered and required_kind_set <= {
            str(records[value].get("kind", "")) for value in selected
        }:
            break

    cursor = 0
    errors: list[str] = []
    while cursor < len(selected):
        current_id = selected[cursor]
        cursor += 1
        for dependency in map(str, records[current_id].get("dependencies", ())):
            if dependency in selected:
                continue
            target = records.get(dependency)
            if target is None or target.get("admitted") is not True:
                errors.append(f"unresolved_dependency:{current_id}:{dependency}")
                continue
            cost = float(target.get("cost", 0.0))
            if len(selected) >= max_items or spent + cost > max_cost:
                errors.append(f"dependency_budget:{current_id}:{dependency}")
                continue
            selected.append(dependency)
            spent += cost

    selected_set = set(selected)
    for candidate_id in sorted(records):
        if candidate_id not in selected_set and candidate_id not in rejected:
            rejected[candidate_id] = "not_needed_after_coverage"
    missing_caps = sorted(required_caps - covered)
    present_kinds = {str(records[value].get("kind", "")) for value in selected}
    missing_kinds = sorted(required_kind_set - present_kinds)
    if missing_caps:
        errors.append("missing_capabilities:" + ",".join(missing_caps))
    if missing_kinds:
        errors.append("missing_kinds:" + ",".join(missing_kinds))
    payload = {
        "selected": tuple(selected),
        "spent": round(spent, 6),
        "covered_capabilities": tuple(sorted(covered)),
        "rejected": tuple(sorted(rejected.items())),
        "complete": not errors and bool(selected),
        "errors": tuple(sorted(set(errors))),
    }
    return {**payload, "package_sha256": stable_hash(payload)}


def _resource_values(value, name, *, nonnegative=True, nonempty=False):
    source = bounded_mapping(value, name, maximum=64)
    if nonempty and not source:
        raise ValueError(f"{name} must declare at least one resource dimension")
    result = {}
    for key, number in source.items():
        key = bounded_text(key, "resource dimension")
        if key in result:
            raise ValueError("resource dimensions must be unique after normalization")
        result[key] = finite_number(number, name, minimum=0 if nonnegative else None)
    return result


def _selection_names(value, name):
    rows = [
        bounded_text(item, name) for item in bounded_sequence(value, name, maximum=256)
    ]
    if len(rows) != len(set(rows)):
        raise ValueError(f"{name} must have unique canonical identities")
    return set(rows)


def reserve_budget(
    *,
    project_id: str,
    work_id: str,
    requested: Mapping[str, float],
    limits: Mapping[str, float],
    active_reservations: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Compute an all-or-none budget proposal; durable acceptance is separate."""
    project_id = bounded_text(project_id, "project identity")
    work_id = bounded_text(work_id, "work identity")
    requested = _resource_values(
        requested, "requested resources", nonnegative=False, nonempty=True
    )
    limits = _resource_values(limits, "resource limits", nonempty=True)
    records = bounded_sequence(
        active_reservations, "active reservations", maximum=10000
    )
    parsed = []
    identities = set()
    dimensions = 0
    for reservation in records:
        reservation = bounded_mapping(reservation, "reservation", maximum=32)
        owner = bounded_text(
            reservation.get("project_id"), "reservation project identity"
        )
        work = bounded_text(reservation.get("work_id"), "reservation work identity")
        identity = bounded_text(
            reservation.get("reservation_id"), "reservation identity"
        )
        if identity in identities:
            raise ValueError("reservation identities must be unique")
        identities.add(identity)
        state = bounded_text(reservation.get("state"), "reservation state")
        if state not in {"active", "denied", "reconciled", "reconciled_with_overage"}:
            raise ValueError("unknown reservation state")
        raw = bounded_mapping(
            reservation.get("reserved"), "reserved resources", maximum=64
        )
        dimensions += len(raw)
        if dimensions > 100000:
            raise ValueError(
                "reservation resource dimensions exceed the aggregate budget"
            )
        reserved = _resource_values(raw, "reserved resources", nonempty=True)
        parsed.append((owner, work, state, reserved))
    used = defaultdict(float)
    for owner, _work, state, reserved in parsed:
        if owner != project_id or state != "active":
            continue
        for name, value in reserved.items():
            used[name] = finite_number(
                used[name] + value, "aggregate active resource usage", minimum=0
            )
    blockers = []
    for name, value in sorted(requested.items()):
        if value < 0:
            blockers.append(f"negative_request:{name}")
        elif name not in limits:
            blockers.append(f"missing_limit:{name}")
        elif (
            finite_number(used[name] + value, "proposed resource usage", minimum=0)
            > limits[name]
        ):
            blockers.append(f"limit_exceeded:{name}")
    payload = {
        "project_id": project_id,
        "work_id": work_id,
        "reserved": dict(sorted(requested.items())),
        "state": "denied" if blockers else "active",
        "blockers": tuple(blockers),
    }
    return {**payload, "reservation_id": "res_" + stable_hash(payload)[:20]}


def reconcile_budget(
    reservation: Mapping[str, object], actual: Mapping[str, float]
) -> dict[str, object]:
    """Reconcile a supplied proposal against complete measured dimensions."""
    reservation = bounded_mapping(reservation, "reservation", maximum=32)
    if reservation.get("state") != "active":
        raise ValueError("only active reservations can be reconciled")
    identity = bounded_text(reservation.get("reservation_id"), "reservation identity")
    project = bounded_text(
        reservation.get("project_id"), "reservation project identity"
    )
    work = bounded_text(reservation.get("work_id"), "reservation work identity")
    reserved = _resource_values(
        reservation.get("reserved"), "reserved resources", nonempty=True
    )
    actual = _resource_values(actual, "actual resources", nonempty=True)
    if set(reserved) - set(actual):
        raise ValueError("actual measurements must cover every reserved dimension")
    overages = tuple(
        sorted(
            name
            for name, value in actual.items()
            if name not in reserved or value > reserved[name]
        )
    )
    payload = {
        "reservation_id": identity,
        "project_id": project,
        "work_id": work,
        "actual": dict(sorted(actual.items())),
        "released": {
            key: max(0.0, value - actual[key])
            for key, value in sorted(reserved.items())
        },
        "state": "reconciled_with_overage" if overages else "reconciled",
        "overages": overages,
    }
    return {**payload, "receipt_sha256": stable_hash(payload)}


def atomic_work_checkout(
    *,
    project_id: str,
    work_id: str,
    expected_version: int,
    current: Mapping[str, object] | None,
    actor_id: str,
) -> dict[str, object]:
    """Create a compare-and-swap work lease without shared mutable ambiguity."""
    current_version = int(current.get("version", 0)) if current else 0
    active = bool(current and current.get("state") == "active")
    granted = current_version == expected_version and not active
    payload = {
        "project_id": project_id,
        "work_id": work_id,
        "actor_id": actor_id,
        "version": current_version + 1 if granted else current_version,
        "state": "active" if granted else "denied",
        "reason": None
        if granted
        else ("already_leased" if active else "version_conflict"),
    }
    return {**payload, "lease_id": "wrk_" + stable_hash(payload)[:20]}


def choose_runtime(
    profiles: Sequence[Mapping[str, object]],
    *,
    project_id: str,
    required_capabilities: Iterable[str],
    minimum_trust: int,
    locality: str | None = None,
) -> dict[str, object]:
    """Filter bounded supplied profiles; physical placement requires its owner."""
    project_id = bounded_text(project_id, "project identity")
    minimum_trust = bounded_integer(
        minimum_trust, "minimum trust", minimum=0, maximum=1000000
    )
    required = _selection_names(required_capabilities, "required capabilities")
    locality = (
        bounded_text(locality, "required locality") if locality is not None else None
    )
    parsed = []
    identities = set()
    for profile in bounded_sequence(profiles, "runtime profiles", maximum=256):
        profile = bounded_mapping(profile, "runtime profile", maximum=32)
        identity = bounded_text(profile.get("id"), "runtime identity")
        if identity in identities:
            raise ValueError("runtime identities must be unique")
        identities.add(identity)
        healthy = profile.get("healthy", False)
        if type(healthy) is not bool:
            raise ValueError("runtime health must be an actual boolean")
        parsed.append(
            {
                "id": identity,
                "healthy": healthy,
                "trust": bounded_integer(
                    profile.get("trust", 0), "runtime trust", minimum=0, maximum=1000000
                ),
                "capabilities": _selection_names(
                    profile.get("capabilities", ()), "runtime capabilities"
                ),
                "scopes": _selection_names(
                    profile.get("project_scopes", ()), "runtime project scopes"
                ),
                "locality": bounded_text(profile["locality"], "runtime locality")
                if "locality" in profile
                else None,
                "quota": finite_number(
                    profile.get("available_quota", 0), "available quota", minimum=0
                ),
                "cost": finite_number(
                    profile.get("cost", 0), "runtime cost", minimum=0
                ),
            }
        )
    eligible = []
    rejected = {}
    for profile in parsed:
        reasons = []
        if not profile["healthy"]:
            reasons.append("unhealthy")
        if profile["trust"] < minimum_trust:
            reasons.append("trust")
        if not required <= profile["capabilities"]:
            reasons.append("capability")
        if project_id not in profile["scopes"]:
            reasons.append("project_scope")
        if locality is not None and profile["locality"] != locality:
            reasons.append("locality")
        if profile["quota"] <= 0:
            reasons.append("quota")
        if reasons:
            rejected[profile["id"]] = tuple(reasons)
        else:
            eligible.append(profile)
    selected = min(eligible, key=lambda row: (row["cost"], row["id"]), default=None)
    payload = {
        "project_id": project_id,
        "selected_runtime": selected["id"] if selected else None,
        "rejected": tuple(sorted(rejected.items())),
        "valid": selected is not None,
    }
    return {**payload, "placement_sha256": stable_hash(payload)}


def transition_job(
    job: Mapping[str, object], target_state: str, *, evidence_ids: Iterable[str] = ()
) -> dict[str, object]:
    """Translate external agent/job states into a sticky canonical lifecycle."""
    allowed = {
        "queued": {"running", "cancelled"},
        "running": TERMINAL_JOB_STATES | {"paused"},
        "paused": {"running", "cancelled", "timed_out"},
    }
    current = str(job.get("state", "queued"))
    if current in TERMINAL_JOB_STATES and target_state != current:
        raise ValueError("terminal job state is sticky")
    if current not in TERMINAL_JOB_STATES and target_state not in allowed.get(
        current, set()
    ):
        raise ValueError(f"invalid transition: {current}->{target_state}")
    evidence = tuple(sorted(set(map(str, evidence_ids))))
    if target_state == "succeeded" and not evidence:
        raise ValueError("success requires outcome evidence")
    payload = {
        "job_id": str(job["job_id"]),
        "project_id": str(job["project_id"]),
        "state": target_state,
        "evidence_ids": evidence,
        "previous_state": current,
    }
    return {**payload, "transition_sha256": stable_hash(payload)}


def query_bitemporal_facts(
    facts: Sequence[Mapping[str, object]],
    *,
    valid_at: str,
    known_at: str,
    project_id: str,
) -> tuple[Mapping[str, object], ...]:
    """Return facts valid in the world and known to the system at separate times."""
    valid_point = datetime.fromisoformat(valid_at.replace("Z", "+00:00"))
    known_point = datetime.fromisoformat(known_at.replace("Z", "+00:00"))

    def point(value: object, fallback: datetime) -> datetime:
        if value in {None, ""}:
            return fallback
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    low = datetime.min.replace(tzinfo=timezone.utc)
    high = datetime.max.replace(tzinfo=timezone.utc)
    selected = []
    for fact in facts:
        if str(fact.get("project_id")) != project_id or fact.get("revoked") is True:
            continue
        valid = (
            point(fact.get("valid_from"), low)
            <= valid_point
            < point(fact.get("valid_to"), high)
        )
        known = (
            point(fact.get("known_from"), low)
            <= known_point
            < point(fact.get("known_to"), high)
        )
        if valid and known:
            selected.append(fact)
    return tuple(sorted(selected, key=lambda item: str(item.get("fact_id", ""))))


def invalidate_dependents(
    changed_fact_ids: Iterable[str], dependencies: Mapping[str, Iterable[str]]
) -> dict[str, object]:
    """Compute bounded transitive invalidation without mutating source facts."""
    changed = set(map(str, changed_fact_ids))
    invalidated = set(changed)
    progressed = True
    while progressed:
        progressed = False
        for dependent, sources in sorted(dependencies.items()):
            if dependent not in invalidated and invalidated & set(map(str, sources)):
                invalidated.add(dependent)
                progressed = True
    payload = {
        "changed": tuple(sorted(changed)),
        "invalidated": tuple(sorted(invalidated - changed)),
    }
    return {**payload, "invalidation_sha256": stable_hash(payload)}


def evaluate_offline_skill_candidate(
    *,
    baseline: Sequence[Mapping[str, object]],
    candidate: Sequence[Mapping[str, object]],
    heldout_case_ids: Iterable[str],
    actor_id: str,
    optimizer_id: str,
    judge_id: str,
    max_regressions: int = 0,
) -> dict[str, object]:
    """Evaluate a quarantined skill candidate without permitting self-promotion."""
    if len({actor_id, optimizer_id, judge_id}) < 3:
        raise ValueError("actor, optimizer, and judge must be distinct")
    base = {str(row["case_id"]): float(row["score"]) for row in baseline}
    proposed = {str(row["case_id"]): float(row["score"]) for row in candidate}
    heldout = set(map(str, heldout_case_ids))
    if heldout - base.keys() or heldout - proposed.keys():
        raise ValueError("held-out cases must exist in both matched rollouts")
    regressions = tuple(sorted(case for case in heldout if proposed[case] < base[case]))
    improvements = tuple(
        sorted(case for case in heldout if proposed[case] > base[case])
    )
    payload = {
        "decision": "proposal_ready"
        if len(regressions) <= max_regressions and improvements
        else "reject",
        "activation": "quarantined_candidate",
        "heldout_cases": tuple(sorted(heldout)),
        "improvements": improvements,
        "regressions": regressions,
        "requires_independent_promotion": True,
    }
    return {**payload, "experiment_sha256": stable_hash(payload)}


def validate_delivery(
    *,
    expected: Mapping[str, object],
    observed: Mapping[str, object],
    domain: str,
) -> dict[str, object]:
    """Validate physical or media promises; generated output is never proof."""
    blockers: list[str] = []
    unknowns: list[str] = []
    for field, promised in sorted(expected.items()):
        if field not in observed:
            unknowns.append(str(field))
        elif observed[field] != promised:
            blockers.append(f"mismatch:{field}")
    if observed.get("provider_downgrade"):
        blockers.append("silent_provider_downgrade")
    if domain in {"cad", "manufacturing", "robotics"}:
        required_checks = {"dimensions", "topology", "interference"}
        if domain == "manufacturing":
            required_checks.add("manufacturability")
        if domain == "robotics":
            required_checks.update({"joint_limits", "frames"})
        passed = set(map(str, observed.get("independent_checks", ())))
        for check in sorted(required_checks - passed):
            blockers.append(f"missing_independent_check:{check}")
    payload = {
        "domain": domain,
        "valid": not blockers and not unknowns,
        "blockers": tuple(blockers),
        "unknowns": tuple(unknowns),
    }
    return {**payload, "validation_sha256": stable_hash(payload)}


def fingerprint_repository(files: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Fingerprint mechanisms and structure without treating a repository as canon."""
    normalized = tuple(
        sorted(
            (
                str(item.get("path", "")).replace("\\", "/"),
                int(item.get("bytes", 0)),
                str(item.get("sha256", "")),
            )
            for item in files
        )
    )
    suffixes: dict[str, int] = defaultdict(int)
    for path, _size, _digest in normalized:
        suffix = path.rsplit(".", 1)[-1].casefold() if "." in path else "none"
        suffixes[suffix] += 1
    payload = {
        "file_count": len(normalized),
        "total_bytes": sum(item[1] for item in normalized),
        "suffix_counts": dict(sorted(suffixes.items())),
        "tree_sha256": stable_hash(normalized),
    }
    return {**payload, "fingerprint_sha256": stable_hash(payload)}


def synthesize_mechanism_delta(
    mechanisms: Sequence[Mapping[str, object]],
    canonical_capability_ids: Iterable[str],
) -> dict[str, object]:
    """Classify mechanism-level novelty; never promote whole repositories."""
    canonical = set(map(str, canonical_capability_ids))
    records = []
    for item in sorted(mechanisms, key=lambda row: str(row.get("mechanism_id", ""))):
        mechanism_id = str(item.get("mechanism_id", ""))
        owner = str(item.get("canonical_owner", ""))
        if not mechanism_id or not item.get("evidence_ids"):
            disposition = "review"
        elif owner in canonical:
            disposition = "enrich"
        else:
            disposition = "novel_candidate"
        records.append((mechanism_id, disposition, owner or None))
    payload = {
        "records": tuple(records),
        "promotion_allowed": False,
        "next_boundary": "knowledge_refinery_admission",
    }
    return {**payload, "delta_sha256": stable_hash(payload)}


def validate_completion_control_workflow(root: Path) -> dict[str, object]:
    """Validate that every consolidated late-intake control is executable."""
    path = root / "orchestration/workflows/completion-controls.yaml"
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    expected = {
        "candidate-pipeline",
        "distributed-runtime",
        "epistemic-evolution",
        "deliverable-validation",
        "research-engine",
    }
    workflows = payload.get("workflows", ())
    ids = {str(item.get("id", "")) for item in workflows if isinstance(item, Mapping)}
    if ids != expected:
        errors.append("completion-control workflow set is incomplete or duplicated")
    for workflow in workflows:
        if not isinstance(workflow, Mapping):
            errors.append("workflow must be an object")
            continue
        steps = workflow.get("steps", ())
        step_ids = {
            str(step.get("id", "")) for step in steps if isinstance(step, Mapping)
        }
        if not steps or "verify" not in step_ids:
            errors.append(f"{workflow.get('id')}: executable verification is missing")
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            unknown = set(map(str, step.get("depends_on", ()))) - step_ids
            if unknown:
                errors.append(
                    f"{workflow.get('id')}:{step.get('id')}: unknown dependencies"
                )
    return {"valid": not errors, "workflow_count": len(ids), "errors": errors}
