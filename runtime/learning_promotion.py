"""Evidence-governed multi-revision learning and promotion primitives.

The module is deliberately CPU-authoritative and side-effect free.  It creates
content-addressed records; callers decide where admitted evidence is retained.
Learning output can become a candidate, but only ``promote_revision`` can emit
a canonical artifact record after every independent gate passes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence


PROMOTABLE_KINDS = {"memory", "knowledge", "skill", "orchestration", "process", "runtime", "script"}
REVISION_STATES = {"observed", "candidate", "shadow", "validated", "canonical", "decayed", "retired"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _valid_hash(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _record(record_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = {"schema_version": "px.learning-promotion/1.0", "record_type": record_type, **dict(payload)}
    return {**body, "record_sha256": content_hash(body)}


def operation_evidence(
    *,
    operation_id: str,
    task_class: str,
    outcome: str,
    measurements: Mapping[str, float | int | bool],
    capability_ids: Sequence[str],
    environment_sha256: str,
    source_refs: Sequence[str],
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Create one immutable observation; it is evidence, never learned truth."""
    if not operation_id.strip() or not task_class.strip() or not source_refs:
        raise ValueError("operation identity, task class, and source references are required")
    if not _valid_hash(environment_sha256):
        raise ValueError("environment_sha256 must be a lowercase SHA-256 value")
    normalized: dict[str, float | int | bool] = {}
    for key, value in sorted(measurements.items()):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("measurements must be finite")
        if not isinstance(value, (int, float, bool)):
            raise ValueError("measurements must be numeric or boolean")
        normalized[str(key)] = value
    return _record(
        "operation_evidence",
        {
            "operation_id": operation_id,
            "task_class": task_class,
            "outcome": outcome,
            "measurements": normalized,
            "capability_ids": sorted(set(map(str, capability_ids))),
            "environment_sha256": environment_sha256,
            "source_refs": sorted(set(map(str, source_refs))),
            "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
            "authority_granted": False,
        },
    )


def aggregate_operations(
    records: Iterable[Mapping[str, Any]], *, metric: str, higher_is_better: bool = True
) -> dict[str, Any]:
    """Build hashless live statistics while anchoring every source evidence hash."""
    rows = tuple(records)
    if not rows:
        raise ValueError("at least one operation record is required")
    hashes = []
    values = []
    task_classes = set()
    for row in rows:
        digest = row.get("record_sha256")
        if row.get("record_type") != "operation_evidence" or not _valid_hash(digest):
            raise ValueError("aggregation accepts only hashed operation evidence")
        value = row.get("measurements", {}).get(metric) if isinstance(row.get("measurements"), Mapping) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"operation evidence is missing finite metric {metric}")
        hashes.append(str(digest))
        values.append(float(value))
        task_classes.add(str(row.get("task_class")))
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
    return {
        "schema_version": "px.learning-aggregation/1.0",
        "record_type": "hashless_aggregation",
        "metric": metric,
        "higher_is_better": higher_is_better,
        "samples": len(values),
        "mean": round(mean, 9),
        "standard_deviation": round(math.sqrt(variance), 9),
        "minimum": min(values),
        "maximum": max(values),
        "task_classes": sorted(task_classes),
        "source_evidence_sha256": sorted(hashes),
        "source_merkle_root": content_hash(sorted(hashes)),
        "aggregation_identity": None,
        "canonical": False,
    }


def extract_pattern(
    *,
    aggregation: Mapping[str, Any],
    interpretation: str,
    applicability: Sequence[str],
) -> dict[str, Any]:
    """Freeze a candidate pattern without granting it learned authority."""
    if (
        aggregation.get("record_type") != "hashless_aggregation"
        or not _valid_hash(aggregation.get("source_merkle_root"))
        or not interpretation.strip()
        or not applicability
    ):
        raise ValueError("pattern extraction requires an aggregation, interpretation, and applicability")
    return _record(
        "pattern_candidate",
        {
            "aggregation_merkle_root": aggregation["source_merkle_root"],
            "metric": aggregation.get("metric"),
            "samples": aggregation.get("samples"),
            "interpretation": interpretation.strip(),
            "applicability": sorted(set(map(str, applicability))),
            "source_evidence_sha256": list(aggregation.get("source_evidence_sha256") or ()),
            "learned_authority": False,
        },
    )


def form_hypothesis(
    *,
    pattern: Mapping[str, Any],
    claim: str,
    success_metric: str,
    incumbent_revision_sha256: str,
    challenger_revision_sha256: str,
) -> dict[str, Any]:
    """Create a testable hypothesis bound to two immutable revisions."""
    if (
        pattern.get("record_type") != "pattern_candidate"
        or not _valid_hash(pattern.get("record_sha256"))
        or not claim.strip()
        or not success_metric.strip()
        or not _valid_hash(incumbent_revision_sha256)
        or not _valid_hash(challenger_revision_sha256)
        or incumbent_revision_sha256 == challenger_revision_sha256
    ):
        raise ValueError("hypothesis requires a hashed pattern, claim, metric, and distinct revisions")
    return _record(
        "hypothesis_candidate",
        {
            "pattern_sha256": pattern["record_sha256"],
            "claim": claim.strip(),
            "success_metric": success_metric.strip(),
            "incumbent_revision_sha256": incumbent_revision_sha256,
            "challenger_revision_sha256": challenger_revision_sha256,
            "validation_required": True,
            "canonical": False,
        },
    )


def confidence_gate(
    *, wins: int, losses: int, ties: int = 0, minimum_trials: int = 6, confidence_z: float = 1.96
) -> dict[str, Any]:
    """Use a conservative Wilson lower bound; ties do not fabricate wins."""
    if min(wins, losses, ties) < 0 or minimum_trials < 1 or confidence_z <= 0:
        raise ValueError("confidence-gate counts and policy are invalid")
    decisive = wins + losses
    trials = decisive + ties
    proportion = wins / decisive if decisive else 0.0
    if decisive:
        denominator = 1 + confidence_z**2 / decisive
        centre = proportion + confidence_z**2 / (2 * decisive)
        margin = confidence_z * math.sqrt((proportion * (1 - proportion) + confidence_z**2 / (4 * decisive)) / decisive)
        lower = (centre - margin) / denominator
    else:
        lower = 0.0
    passed = trials >= minimum_trials and decisive > 0 and lower > 0.5
    return _record(
        "confidence_gate",
        {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "trials": trials,
            "minimum_trials": minimum_trials,
            "confidence_z": confidence_z,
            "win_rate": round(proportion, 9),
            "wilson_lower_bound": round(lower, 9),
            "passed": passed,
            "reason": "candidate advantage clears the confidence boundary" if passed else "insufficient evidence for promotion",
        },
    )


def freeze_revision(
    *,
    unit_id: str,
    kind: str,
    artifact: object,
    evidence_sha256: Sequence[str],
    dependency_sha256: Mapping[str, str] | None = None,
    parent_revision_sha256: str | None = None,
    tier: int = 1,
) -> dict[str, Any]:
    if kind not in PROMOTABLE_KINDS or not unit_id.strip() or tier not in {1, 2, 3, 4, 5}:
        raise ValueError("revision identity, kind, or tier is invalid")
    evidence = sorted(set(map(str, evidence_sha256)))
    dependencies = dict(sorted((dependency_sha256 or {}).items()))
    if not evidence or any(not _valid_hash(value) for value in (*evidence, *dependencies.values())):
        raise ValueError("current evidence and dependency hashes are required")
    if parent_revision_sha256 is not None and not _valid_hash(parent_revision_sha256):
        raise ValueError("parent revision hash is invalid")
    identity = {
        "unit_id": unit_id,
        "kind": kind,
        "artifact_sha256": content_hash(artifact),
        "dependency_sha256": dependencies,
        "parent_revision_sha256": parent_revision_sha256,
        "tier": tier,
    }
    return _record(
        "frozen_revision",
        {
            **identity,
            "revision_sha256": content_hash(identity),
            "state": "candidate"
            if tier == 1
            else "shadow"
            if tier in {2, 3}
            else "validated",
            "artifact": artifact,
            "evidence_sha256": evidence,
            "immutable": True,
            "canonical": False,
        },
    )


def compare_revisions(
    *, incumbent: Mapping[str, Any], challenger: Mapping[str, Any], trials: Sequence[Mapping[str, Any]], minimum_trials: int = 6
) -> dict[str, Any]:
    for revision in (incumbent, challenger):
        if revision.get("record_type") != "frozen_revision" or not _valid_hash(revision.get("revision_sha256")):
            raise ValueError("A/B comparison requires frozen revisions")
    wins = losses = ties = 0
    evidence = []
    for trial in trials:
        if not _valid_hash(trial.get("evidence_sha256")):
            raise ValueError("every A/B trial requires hashed evidence")
        winner = str(trial.get("winner"))
        if winner == "challenger":
            wins += 1
        elif winner == "incumbent":
            losses += 1
        elif winner == "tie":
            ties += 1
        else:
            raise ValueError("trial winner must be challenger, incumbent, or tie")
        evidence.append(str(trial["evidence_sha256"]))
    gate = confidence_gate(wins=wins, losses=losses, ties=ties, minimum_trials=minimum_trials)
    return _record(
        "ab_comparison",
        {
            "incumbent_revision_sha256": incumbent["revision_sha256"],
            "challenger_revision_sha256": challenger["revision_sha256"],
            "trial_evidence_sha256": sorted(evidence),
            "gate": gate,
            "passed": gate["passed"],
            "loser_retention_required": True,
        },
    )


def research_validation(
    *, question: str, references: Sequence[Mapping[str, Any]], better_alternative_found: bool, conclusion: str
) -> dict[str, Any]:
    if not question.strip() or not conclusion.strip() or not references:
        raise ValueError("research question, conclusion, and references are required")
    normalized = []
    for reference in references:
        if not str(reference.get("uri", "")).strip() or not _valid_hash(reference.get("evidence_sha256")):
            raise ValueError("research references require URI and evidence hash")
        normalized.append({"uri": str(reference["uri"]), "evidence_sha256": str(reference["evidence_sha256"]), "independent": bool(reference.get("independent", True))})
    passed = any(item["independent"] for item in normalized)
    return _record(
        "research_validation",
        {"question": question, "references": sorted(normalized, key=lambda item: item["uri"]), "better_alternative_found": better_alternative_found, "conclusion": conclusion, "passed": passed},
    )


def dependency_invalidation(revision: Mapping[str, Any], current: Mapping[str, str]) -> dict[str, Any]:
    expected = revision.get("dependency_sha256", {})
    if not isinstance(expected, Mapping):
        raise ValueError("revision dependency hashes are invalid")
    stale = sorted(key for key, digest in expected.items() if current.get(str(key)) != digest)
    return _record("dependency_invalidation", {"revision_sha256": revision.get("revision_sha256"), "stale_dependencies": stale, "valid": not stale})


def promote_revision(
    *,
    revision: Mapping[str, Any],
    confidence: Mapping[str, Any],
    comparison: Mapping[str, Any],
    research: Mapping[str, Any],
    final_validation_sha256: str,
    current_dependencies: Mapping[str, str],
    partial_units: Sequence[str] = (),
) -> dict[str, Any]:
    """Emit a canonical corpus identity only after all four gates pass."""
    invalidation = dependency_invalidation(revision, current_dependencies)
    checks = {
        "frozen_revision": revision.get("record_type") == "frozen_revision" and revision.get("immutable") is True,
        "confidence_gate": confidence.get("record_type") == "confidence_gate" and confidence.get("passed") is True,
        "ab_gate": comparison.get("record_type") == "ab_comparison" and comparison.get("passed") is True,
        "research_gate": research.get("record_type") == "research_validation" and research.get("passed") is True,
        "final_validation": _valid_hash(final_validation_sha256),
        "dependencies_current": invalidation["valid"] is True,
    }
    passed = all(checks.values())
    canonical_identity = {
        "unit_id": revision.get("unit_id"),
        "kind": revision.get("kind"),
        "revision_sha256": revision.get("revision_sha256"),
        "artifact_sha256": revision.get("artifact_sha256"),
        "partial_units": sorted(set(map(str, partial_units))),
        "dependency_sha256": dict(sorted(current_dependencies.items())),
    }
    return _record(
        "promotion_decision",
        {
            "passed": passed,
            "checks": checks,
            "canonical_corpus_sha256": content_hash(canonical_identity) if passed else None,
            "canonical_identity": canonical_identity if passed else None,
            "state": "canonical" if passed else "candidate",
            "source_gate_sha256": sorted(filter(None, [confidence.get("record_sha256"), comparison.get("record_sha256"), research.get("record_sha256"), final_validation_sha256, invalidation.get("record_sha256")])),
            "learning_direct_write_allowed": False,
            "loser_retention_required": True,
            "rollback_revision_sha256": comparison.get("incumbent_revision_sha256") if passed else None,
        },
    )


def measure_reuse(*, promotion_sha256: str, uses: int, successes: int, regressions: int) -> dict[str, Any]:
    if not _valid_hash(promotion_sha256) or min(uses, successes, regressions) < 0 or successes + regressions > uses:
        raise ValueError("reuse measurement is invalid")
    return _record("reuse_measurement", {"promotion_sha256": promotion_sha256, "uses": uses, "successes": successes, "regressions": regressions, "success_rate": round(successes / uses, 9) if uses else None})


def decay_decision(measurement: Mapping[str, Any], *, minimum_uses: int = 10, minimum_success_rate: float = 0.7, maximum_regressions: int = 2) -> dict[str, Any]:
    if measurement.get("record_type") != "reuse_measurement" or not 0 <= minimum_success_rate <= 1:
        raise ValueError("decay decision requires a reuse measurement and valid policy")
    enough = int(measurement.get("uses", 0)) >= minimum_uses
    decay = enough and (float(measurement.get("success_rate") or 0) < minimum_success_rate or int(measurement.get("regressions", 0)) > maximum_regressions)
    return _record("decay_decision", {"measurement_sha256": measurement.get("record_sha256"), "enough_evidence": enough, "decay": decay, "next_state": "decayed" if decay else "canonical", "automatic_delete_allowed": False})


def hash_tree(units: Mapping[str, object], dependencies: Mapping[str, Sequence[str]] = {}) -> dict[str, Any]:
    """Create hierarchical hashes and a deterministic dependency invalidation map."""
    hashes = {key: content_hash(value) for key, value in sorted(units.items())}
    unknown = sorted({dependency for values in dependencies.values() for dependency in values if dependency not in hashes})
    if unknown:
        raise ValueError("unknown hash-tree dependencies: " + ", ".join(unknown))
    rows = {key: {"sha256": hashes[key], "dependencies": sorted(set(map(str, dependencies.get(key, ())))) } for key in hashes}
    return _record("hash_tree", {"units": rows, "root_sha256": content_hash(rows)})


def _typed_record(value: object, record_type: str, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    body = {str(key): item for key, item in value.items() if key != "record_sha256"}
    if (
        value.get("schema_version") != "px.learning-promotion/1.0"
        or value.get("record_type") != record_type
        or not _valid_hash(value.get("record_sha256"))
        or value.get("record_sha256") != content_hash(body)
    ):
        raise ValueError(f"{label} record identity is invalid")
    return value


def _frozen_revision(value: object, label: str, *, tier: int | None = None) -> Mapping[str, Any]:
    revision = _typed_record(value, "frozen_revision", label)
    expected = freeze_revision(
        unit_id=str(revision.get("unit_id") or ""),
        kind=str(revision.get("kind") or ""),
        artifact=revision.get("artifact"),
        evidence_sha256=list(revision.get("evidence_sha256") or ()),
        dependency_sha256=dict(revision.get("dependency_sha256") or {}),
        parent_revision_sha256=revision.get("parent_revision_sha256"),
        tier=int(revision.get("tier", 0)),
    )
    if dict(revision) != expected or (tier is not None and revision.get("tier") != tier):
        raise ValueError(f"{label} semantic identity is invalid")
    return revision


def _comparison(
    value: object,
    label: str,
    *,
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    comparison = _typed_record(value, "ab_comparison", label)
    gate = _typed_record(comparison.get("gate"), "confidence_gate", f"{label} confidence gate")
    if gate.get("minimum_trials") != 6 or gate.get("confidence_z") != 1.96:
        raise ValueError(f"{label} confidence policy is invalid")
    expected = compare_revisions(
        incumbent=incumbent,
        challenger=challenger,
        trials=trials,
        minimum_trials=6,
    )
    if dict(comparison) != expected:
        raise ValueError(f"{label} revision or evidence binding is invalid")
    return comparison


def validate_learning_pipeline_state(state: Mapping[str, Any]) -> None:
    """Recompute every present learning hash according to its semantic role.

    A pipeline, frozen revision, record, artifact, evidence item, promotion
    decision, and canonical corpus intentionally have different identities.
    This parser validates their typed commitments and links; it never treats
    equality between unrelated hash roles as an integrity condition.
    """
    if not isinstance(state, Mapping) or len(canonical_json(state).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("learning pipeline state is invalid or exceeds the 2 MiB bound")

    evidence_records: list[Mapping[str, Any]] = []
    for index, value in enumerate(state.get("operation_evidence") or ()):
        record = _typed_record(value, "operation_evidence", f"operation evidence {index}")
        expected = operation_evidence(
            operation_id=str(record.get("operation_id") or ""),
            task_class=str(record.get("task_class") or ""),
            outcome=str(record.get("outcome") or ""),
            measurements=dict(record.get("measurements") or {}),
            capability_ids=list(record.get("capability_ids") or ()),
            environment_sha256=str(record.get("environment_sha256") or ""),
            source_refs=list(record.get("source_refs") or ()),
            observed_at=str(record.get("observed_at") or ""),
        )
        if dict(record) != expected:
            raise ValueError(f"operation evidence {index} semantic identity is invalid")
        evidence_records.append(record)
    evidence_hashes = sorted(str(item["record_sha256"]) for item in evidence_records)

    aggregation = state.get("aggregation")
    if aggregation is not None:
        if (
            not isinstance(aggregation, Mapping)
            or aggregation.get("schema_version") != "px.learning-aggregation/1.0"
            or aggregation.get("record_type") != "hashless_aggregation"
            or aggregation.get("aggregation_identity") is not None
            or "record_sha256" in aggregation
            or aggregation.get("source_evidence_sha256") != evidence_hashes
            or aggregation.get("source_merkle_root") != content_hash(evidence_hashes)
        ):
            raise ValueError("hashless aggregation evidence binding is invalid")
        expected_aggregation = aggregate_operations(
            evidence_records,
            metric=str(aggregation.get("metric") or ""),
            higher_is_better=bool(aggregation.get("higher_is_better")),
        )
        if dict(aggregation) != expected_aggregation:
            raise ValueError("hashless aggregation statistics are invalid")

    pattern = state.get("pattern")
    if pattern is not None:
        if not isinstance(aggregation, Mapping):
            raise ValueError("pattern requires its hashless aggregation")
        parsed_pattern = _typed_record(pattern, "pattern_candidate", "pattern candidate")
        expected_pattern = extract_pattern(
            aggregation=aggregation,
            interpretation=str(parsed_pattern.get("interpretation") or ""),
            applicability=list(parsed_pattern.get("applicability") or ()),
        )
        if dict(parsed_pattern) != expected_pattern:
            raise ValueError("pattern candidate aggregation binding is invalid")

    incumbent = state.get("incumbent_revision")
    challenger = state.get("challenger_revision")
    secondary = state.get("secondary_revision")
    parsed_incumbent = _frozen_revision(incumbent, "incumbent revision", tier=1) if incumbent is not None else None
    parsed_challenger = _frozen_revision(challenger, "challenger revision", tier=2) if challenger is not None else None
    parsed_secondary = _frozen_revision(secondary, "secondary revision", tier=3) if secondary is not None else None
    if parsed_challenger is not None:
        if parsed_incumbent is None or any(
            parsed_challenger.get(field) != parsed_incumbent.get(field)
            for field in ("unit_id", "kind", "dependency_sha256")
        ) or parsed_challenger.get("parent_revision_sha256") != parsed_incumbent.get("revision_sha256"):
            raise ValueError("challenger revision ancestry is invalid")
    if parsed_secondary is not None:
        if parsed_challenger is None or any(
            parsed_secondary.get(field) != parsed_challenger.get(field)
            for field in ("unit_id", "kind", "dependency_sha256")
        ) or parsed_secondary.get("parent_revision_sha256") != parsed_challenger.get("revision_sha256"):
            raise ValueError("secondary revision ancestry is invalid")

    hypothesis = state.get("hypothesis")
    if hypothesis is not None:
        if pattern is None or parsed_incumbent is None or parsed_challenger is None:
            raise ValueError("hypothesis requires its pattern and frozen revisions")
        parsed_hypothesis = _typed_record(hypothesis, "hypothesis_candidate", "hypothesis candidate")
        expected_hypothesis = form_hypothesis(
            pattern=pattern,
            claim=str(parsed_hypothesis.get("claim") or ""),
            success_metric=str(parsed_hypothesis.get("success_metric") or ""),
            incumbent_revision_sha256=str(parsed_incumbent["revision_sha256"]),
            challenger_revision_sha256=str(parsed_challenger["revision_sha256"]),
        )
        if dict(parsed_hypothesis) != expected_hypothesis:
            raise ValueError("hypothesis revision binding is invalid")

    trials = [dict(item) for item in state.get("trials") or () if isinstance(item, Mapping)]
    if len(trials) != len(state.get("trials") or ()):
        raise ValueError("primary trials must be objects")
    comparison = state.get("comparison")
    parsed_comparison = None
    if comparison is not None:
        if parsed_incumbent is None or parsed_challenger is None:
            raise ValueError("primary comparison requires frozen revisions")
        parsed_comparison = _comparison(
            comparison,
            "primary comparison",
            incumbent=parsed_incumbent,
            challenger=parsed_challenger,
            trials=trials,
        )

    research = state.get("research")
    parsed_research = None
    if research is not None:
        parsed_research = _typed_record(research, "research_validation", "research validation")
        expected_research = research_validation(
            question=str(parsed_research.get("question") or ""),
            references=list(parsed_research.get("references") or ()),
            better_alternative_found=bool(parsed_research.get("better_alternative_found")),
            conclusion=str(parsed_research.get("conclusion") or ""),
        )
        if dict(parsed_research) != expected_research:
            raise ValueError("research validation evidence binding is invalid")

    secondary_trials = [dict(item) for item in state.get("secondary_trials") or () if isinstance(item, Mapping)]
    if len(secondary_trials) != len(state.get("secondary_trials") or ()):
        raise ValueError("secondary trials must be objects")
    secondary_comparison = state.get("secondary_comparison")
    parsed_secondary_comparison = None
    if secondary_comparison is not None:
        if parsed_challenger is None or parsed_secondary is None:
            raise ValueError("secondary comparison requires frozen revisions")
        parsed_secondary_comparison = _comparison(
            secondary_comparison,
            "secondary comparison",
            incumbent=parsed_challenger,
            challenger=parsed_secondary,
            trials=secondary_trials,
        )
    reverse_comparison = state.get("secondary_incumbent_comparison")
    if reverse_comparison is not None:
        if parsed_challenger is None or parsed_secondary is None:
            raise ValueError("secondary incumbent comparison requires frozen revisions")
        reversed_trials = [
            {
                **trial,
                "winner": "challenger" if trial.get("winner") == "incumbent" else "incumbent" if trial.get("winner") == "challenger" else "tie",
            }
            for trial in secondary_trials
        ]
        _comparison(
            reverse_comparison,
            "secondary incumbent comparison",
            incumbent=parsed_secondary,
            challenger=parsed_challenger,
            trials=reversed_trials,
        )

    selected = state.get("selected_revision")
    parsed_selected = None
    if selected is not None:
        candidates = [item for item in (parsed_incumbent, parsed_challenger, parsed_secondary) if item is not None]
        matches = [item for item in candidates if dict(item) == dict(selected)] if isinstance(selected, Mapping) else []
        if len(matches) != 1:
            raise ValueError("selected revision is not one exact frozen revision")
        parsed_selected = matches[0]
        selection = state.get("selection_comparison")
        available = [item for item in (parsed_comparison, parsed_secondary_comparison) if item is not None]
        if not isinstance(selection, Mapping) or not any(dict(selection) == dict(item) for item in available):
            raise ValueError("selected revision comparison binding is invalid")
        if selection.get("challenger_revision_sha256") != parsed_selected.get("revision_sha256"):
            raise ValueError("selected revision does not match the winning comparison role")

    final_validation = state.get("final_validation")
    if final_validation is not None and (
        not isinstance(final_validation, Mapping)
        or final_validation.get("schema_version") != "px.learning-final-validation/1.0"
        or not _valid_hash(final_validation.get("evidence_sha256"))
    ):
        raise ValueError("final validation evidence identity is invalid")

    decision = state.get("promotion_decision")
    parsed_decision = None
    if decision is not None:
        parsed_decision = _typed_record(decision, "promotion_decision", "promotion decision")
        checks = parsed_decision.get("checks")
        if not isinstance(checks, Mapping) or not all(isinstance(value, bool) for value in checks.values()):
            raise ValueError("promotion decision checks are invalid")
        if parsed_decision.get("passed") is not all(checks.values()):
            raise ValueError("promotion decision result is inconsistent with its gates")
        if parsed_decision.get("passed") is True:
            if (
                parsed_selected is None
                or not isinstance(state.get("selection_comparison"), Mapping)
                or parsed_research is None
                or not isinstance(final_validation, Mapping)
                or not isinstance(parsed_decision.get("canonical_identity"), Mapping)
            ):
                raise ValueError("passed promotion decision is missing typed inputs")
            canonical_identity = parsed_decision["canonical_identity"]
            expected_decision = promote_revision(
                revision=parsed_selected,
                confidence=state["selection_comparison"]["gate"],
                comparison=state["selection_comparison"],
                research=parsed_research,
                final_validation_sha256=str(final_validation["evidence_sha256"]),
                current_dependencies=dict(canonical_identity.get("dependency_sha256") or {}),
                partial_units=list(canonical_identity.get("partial_units") or ()),
            )
            if dict(parsed_decision) != expected_decision:
                raise ValueError("promotion decision or canonical corpus binding is invalid")
        elif any(parsed_decision.get(field) is not None for field in ("canonical_identity", "canonical_corpus_sha256", "rollback_revision_sha256")):
            raise ValueError("failed promotion decision cannot claim canonical identities")

    measurements: list[Mapping[str, Any]] = []
    for index, value in enumerate(state.get("reuse_measurements") or ()):
        measurement = _typed_record(value, "reuse_measurement", f"reuse measurement {index}")
        if parsed_decision is None or measurement.get("promotion_sha256") != parsed_decision.get("record_sha256"):
            raise ValueError(f"reuse measurement {index} promotion binding is invalid")
        expected_measurement = measure_reuse(
            promotion_sha256=str(measurement.get("promotion_sha256") or ""),
            uses=int(measurement.get("uses", -1)),
            successes=int(measurement.get("successes", -1)),
            regressions=int(measurement.get("regressions", -1)),
        )
        if dict(measurement) != expected_measurement:
            raise ValueError(f"reuse measurement {index} semantic identity is invalid")
        measurements.append(measurement)
    decay = state.get("decay_decision")
    if decay is not None:
        if not measurements:
            raise ValueError("decay decision requires a reuse measurement")
        parsed_decay = _typed_record(decay, "decay_decision", "decay decision")
        if dict(parsed_decay) != decay_decision(measurements[-1]):
            raise ValueError("decay decision measurement binding is invalid")

    for field in ("knowledge_candidate_sha256",):
        if state.get(field) is not None and not _valid_hash(state.get(field)):
            raise ValueError(f"{field} must be a lowercase SHA-256 value")
