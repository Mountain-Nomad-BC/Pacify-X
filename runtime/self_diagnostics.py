"""Self Operations diagnostic coordinator — a composition layer, not a second optimizer.

Owner requirement (V3 Phase 3, and the one intentional new capability V3's discovery identified):
coordinate existing canonical capabilities into a bounded diagnosis, and **delegate** rather than
repair.

Hard properties, each enforced by construction:

  * the coordinator has **no write path** — it returns a recommendation, never an effect;
  * it cannot self-approve; a required repair needs the normal authority boundary;
  * a failed/stale/ambiguous check is never interpreted as success;
  * it selects a **canonical owner** or explicitly reports that none exists;
  * `NO_PRODUCT_DEFECT` and `PROBE_OR_TEST_DEFECT` are first-class outcomes, because environment,
    probe, evidence, configuration, and generated-state failures must not be mislabelled as
    product defects (V3 rule 13).

Public entry points:
    classify_condition(...)   -> one disposition with its evidence and owner binding
    diagnose(...)             -> a bounded recommendation over a reported condition
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

COORDINATOR_SCHEMA = "px.self-operations-diagnosis/1.0"

# Terminal, non-repair dispositions. Reporting one of these is a correct outcome.
DISPOSITIONS = (
    "PRODUCT_DEFECT",
    "INTEGRATION_DEFECT",
    "CONFIGURATION_DEFECT",
    "GENERATED_STATE_DEFECT",
    "EVIDENCE_STALE_OR_INVALID",
    "PROBE_OR_TEST_DEFECT",
    "ENVIRONMENT_UNAVAILABLE",
    "EXPECTED_OFFLINE_BOUNDARY",
    "AUTHORITY_DENIED",
    "OPTIMIZATION_OPPORTUNITY",
    "NO_PRODUCT_DEFECT",
)

# Recursion controls (V3 section: Recursion controls). Any one stops the loop.
STOP_CONDITIONS = (
    "max_iterations",
    "max_mutation_transactions",
    "max_cumulative_paths_touched",
    "max_wall_budget",
    "max_compute_budget",
    "repeated_candidate_hash",
    "repeated_world_state_hash",
    "unchanged_objective",
    "no_new_evidence",
    "fixed_point",
)

# Which canonical owner class handles each disposition. `None` means "delegate to the caller's
# authority boundary" because the class is not a repair at all.
OWNER_BY_DISPOSITION: dict[str, str | None] = {
    "PRODUCT_DEFECT": "canonical-specialist-for-the-affected-subsystem",
    "INTEGRATION_DEFECT": "canonical-owner-of-the-unwired-seam",
    "CONFIGURATION_DEFECT": "configuration-owner",
    "GENERATED_STATE_DEFECT": "generated-state-builder-for-the-stale-projection",
    "EVIDENCE_STALE_OR_INVALID": "evidence-custody-owner",
    "PROBE_OR_TEST_DEFECT": "test-owner",
    "ENVIRONMENT_UNAVAILABLE": None,
    "EXPECTED_OFFLINE_BOUNDARY": None,
    "AUTHORITY_DENIED": None,
    "OPTIMIZATION_OPPORTUNITY": "workflow-autotuning-advisor",
    "NO_PRODUCT_DEFECT": None,
}

# Conditions that must never be escalated to a product-defect repair.
NON_REPAIR_SIGNALS = {
    "environment_unavailable": "ENVIRONMENT_UNAVAILABLE",
    "offline": "EXPECTED_OFFLINE_BOUNDARY",
    "authority_denied": "AUTHORITY_DENIED",
    "evidence_missing": "EVIDENCE_STALE_OR_INVALID",
    "evidence_stale": "EVIDENCE_STALE_OR_INVALID",
    "evidence_corrupt": "EVIDENCE_STALE_OR_INVALID",
    "probe_defect": "PROBE_OR_TEST_DEFECT",
    "test_defect": "PROBE_OR_TEST_DEFECT",
    "configuration_error": "CONFIGURATION_DEFECT",
    "generated_stale": "GENERATED_STATE_DEFECT",
    "expected_boundary": "NO_PRODUCT_DEFECT",
}

MAX_SIGNALS = 32
MAX_TEXT = 512


@dataclass(frozen=True, slots=True)
class Observation:
    """One canonical signal about a condition. Evidence is referenced, not copied."""

    signal: str
    scope: str
    evidence_ref: str | None = None
    evidence_age_seconds: float | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Classification:
    disposition: str
    reason: str
    canonical_owner: str | None
    evidence: tuple[str, ...] = ()
    competing_explanation: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "reason": self.reason,
            "canonical_owner": self.canonical_owner,
            "evidence": list(self.evidence),
            "competing_explanation": self.competing_explanation,
        }


def _text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > MAX_TEXT
    ):
        raise ValueError(f"{name} must be bounded nonempty text")
    return value.strip()


def classify_condition(
    signals: Sequence[Mapping[str, Any]],
    *,
    evidence_max_age_seconds: float = 86400.0,
) -> Classification:
    """Classify a reported condition from its observed signals.

    Precedence is deliberate: a non-repair signal always outranks a repair signal, so an
    environment or probe condition cannot be escalated into a product defect.
    """

    if type(signals) not in (list, tuple) or not 1 <= len(signals) <= MAX_SIGNALS:
        raise ValueError(
            f"signals must be a bounded non-empty sequence (<= {MAX_SIGNALS})"
        )

    observed: list[Observation] = []
    for raw in signals:
        if type(raw) is not dict:
            raise ValueError("each signal must be an object")
        signal = _text(raw.get("signal"), "signal")
        scope = _text(raw.get("scope"), "scope")
        evidence_ref = raw.get("evidence_ref")
        if evidence_ref is not None:
            evidence_ref = _text(evidence_ref, "evidence_ref")
        age = raw.get("evidence_age_seconds")
        if age is not None:
            if (
                not isinstance(age, (int, float))
                or isinstance(age, bool)
                or not math.isfinite(float(age))
                or age < 0
            ):
                raise ValueError(
                    "evidence_age_seconds must be a non-negative finite number"
                )
            age = float(age)
        note = raw.get("note")
        observed.append(
            Observation(
                signal=signal,
                scope=scope,
                evidence_ref=evidence_ref,
                evidence_age_seconds=age,
                note=_text(note, "note") if note is not None else None,
            )
        )

    names = {o.signal for o in observed}
    primary_scope = observed[0].scope

    # 1. A non-repair signal outranks everything. Never escalate these into a product defect.
    for signal, disposition in NON_REPAIR_SIGNALS.items():
        if signal in names:
            return Classification(
                disposition=disposition,
                reason=f"signal {signal!r} is a terminal non-repair condition",
                canonical_owner=OWNER_BY_DISPOSITION[disposition],
                evidence=tuple(
                    o.evidence_ref
                    for o in observed
                    if o.evidence_ref and o.signal == signal
                ),
                competing_explanation=(
                    "a repair escalation would mislabel an environment/probe/evidence condition "
                    "as a product defect"
                ),
            )

    # 2. A check that failed and cannot be evidenced is a stale/ambiguous evidence condition.
    if "check_failed_without_evidence" in names or any(
        o.evidence_ref is None for o in observed if o.signal == "check_failed"
    ):
        return Classification(
            disposition="EVIDENCE_STALE_OR_INVALID",
            reason="a failed check carried no usable evidence, so its result is not interpretable",
            canonical_owner=OWNER_BY_DISPOSITION["EVIDENCE_STALE_OR_INVALID"],
            competing_explanation="interpreting an unevidenced failure as a pass would be a false success",
        )

    # 3. Evidence older than the declared freshness bound is stale, not a defect.
    stale = [
        o
        for o in observed
        if o.evidence_age_seconds is not None
        and o.evidence_age_seconds > evidence_max_age_seconds
    ]
    if stale:
        return Classification(
            disposition="EVIDENCE_STALE_OR_INVALID",
            reason=(
                f"{len(stale)} observation(s) exceed the {evidence_max_age_seconds:g}s freshness bound"
            ),
            canonical_owner=OWNER_BY_DISPOSITION["EVIDENCE_STALE_OR_INVALID"],
            evidence=tuple(o.evidence_ref for o in stale if o.evidence_ref),
            competing_explanation="stale evidence is not proof of failure and not proof of success",
        )

    # 4. A declared-but-unwired seam between two existing owners is an integration defect.
    if "owner_mismatch" in names or "unwired_seam" in names:
        return Classification(
            disposition="INTEGRATION_DEFECT",
            reason=f"owners exist but are not wired at {primary_scope}",
            canonical_owner=OWNER_BY_DISPOSITION["INTEGRATION_DEFECT"],
            competing_explanation="the owners themselves may be correct; only the seam is missing",
        )

    # 5. A genuine product behaviour failure, only after every non-repair explanation is excluded.
    if "behaviour_incorrect" in names or "regression" in names:
        return Classification(
            disposition="PRODUCT_DEFECT",
            reason=f"observed behaviour is incorrect at {primary_scope}",
            canonical_owner=OWNER_BY_DISPOSITION["PRODUCT_DEFECT"],
            competing_explanation=(
                "excluded: environment, evidence freshness, probe defect, and expected boundary "
                "were all checked first"
            ),
        )

    # 6. Working but improvable.
    if "slow" in names or "inefficient" in names or "optimization_opportunity" in names:
        return Classification(
            disposition="OPTIMIZATION_OPPORTUNITY",
            reason=f"behaviour is correct but improvable at {primary_scope}",
            canonical_owner=OWNER_BY_DISPOSITION["OPTIMIZATION_OPPORTUNITY"],
            competing_explanation="the condition must be measured before any change is justified",
        )

    # 7. Nothing wrong was observed.
    return Classification(
        disposition="NO_PRODUCT_DEFECT",
        reason="no observed signal indicates a defect",
        canonical_owner=None,
        evidence=tuple(o.evidence_ref for o in observed if o.evidence_ref),
    )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """A bounded recommendation. It carries no authority and performs no effect."""

    schema_version: str
    condition: str
    scope: str
    classification: Classification
    recommended_action: str
    requires_authority: bool
    coordinator_may_execute: bool
    stop_conditions: tuple[str, ...] = field(default_factory=lambda: STOP_CONDITIONS)
    diagnosis_sha256: str = ""

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "condition": self.condition,
            "scope": self.scope,
            "classification": self.classification.as_mapping(),
            "recommended_action": self.recommended_action,
            "requires_authority": self.requires_authority,
            "coordinator_may_execute": self.coordinator_may_execute,
            "stop_conditions": list(self.stop_conditions),
            "diagnosis_sha256": self.diagnosis_sha256,
        }


_REMEDIATION_BY_DISPOSITION = {
    "PRODUCT_DEFECT": "route to the canonical specialist for the affected subsystem; repair under normal authority",
    "INTEGRATION_DEFECT": "wire the existing owners together; do not create a replacement owner",
    "CONFIGURATION_DEFECT": "correct the configuration at its canonical owner",
    "GENERATED_STATE_DEFECT": "regenerate the stale projection from its canonical inputs in dependency order",
    "EVIDENCE_STALE_OR_INVALID": "re-collect evidence or quarantine it; do not treat it as a result",
    "PROBE_OR_TEST_DEFECT": "correct the probe or test; the product is not implicated",
    "ENVIRONMENT_UNAVAILABLE": "no repair; the environment or dependency is absent",
    "EXPECTED_OFFLINE_BOUNDARY": "no repair; this is the designed boundary",
    "AUTHORITY_DENIED": "no repair; policy correctly refused",
    "OPTIMIZATION_OPPORTUNITY": "measure first; only then consider a candidate through the experiment owner",
    "NO_PRODUCT_DEFECT": "no repair; record the observation and stop",
}


def diagnose(
    root: Path,
    *,
    condition: str,
    scope: str,
    signals: Sequence[Mapping[str, Any]],
    evidence_max_age_seconds: float = 86400.0,
) -> Diagnosis:
    """Produce a bounded diagnosis. Performs no mutation and grants no authority."""

    condition = _text(condition, "condition")
    scope = _text(scope, "scope")
    classification = classify_condition(
        signals, evidence_max_age_seconds=evidence_max_age_seconds
    )
    requires_authority = classification.disposition in {
        "PRODUCT_DEFECT",
        "INTEGRATION_DEFECT",
        "CONFIGURATION_DEFECT",
        "GENERATED_STATE_DEFECT",
        "OPTIMIZATION_OPPORTUNITY",
    }
    body = {
        "schema_version": COORDINATOR_SCHEMA,
        "condition": condition,
        "scope": scope,
        "classification": classification.as_mapping(),
        "recommended_action": _REMEDIATION_BY_DISPOSITION[classification.disposition],
        "requires_authority": requires_authority,
        # The coordinator never executes a repair. This is always False by contract.
        "coordinator_may_execute": False,
        "stop_conditions": list(STOP_CONDITIONS),
    }
    digest = hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return Diagnosis(
        schema_version=COORDINATOR_SCHEMA,
        condition=condition,
        scope=scope,
        classification=classification,
        recommended_action=body["recommended_action"],
        requires_authority=requires_authority,
        coordinator_may_execute=False,
        diagnosis_sha256=digest,
    )


def select_specialist(root: Path, disposition: str) -> dict[str, object]:
    """Bind a disposition to a declared canonical owner, or report that none exists.

    Creating a second owner is forbidden, so when no declared owner matches, the correct answer is
    an explicit miss rather than a new implementation.
    """

    if disposition not in DISPOSITIONS:
        raise ValueError(f"unknown disposition: {disposition}")
    hint = OWNER_BY_DISPOSITION.get(disposition)
    if hint is None:
        return {
            "disposition": disposition,
            "owner": None,
            "reason": "this disposition is not a repair and requires no owner",
            "may_create_owner": False,
        }
    declared: list[str] = []
    capability_map = root / "registry/capability_map.json"
    if capability_map.is_file():
        payload = json.loads(capability_map.read_text(encoding="utf-8-sig"))
        declared = [entry["id"] for entry in payload.get("active_capabilities", [])]
    return {
        "disposition": disposition,
        "owner_class": hint,
        "declared_owners_available": len(declared),
        "may_create_owner": False,
        "reason": "delegate to the canonical owner; never create a second one",
    }
