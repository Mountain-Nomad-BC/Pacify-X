"""Typed feature-acceptance claims kept separate from control interaction proof."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


REVISIONS = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

EVIDENCE_CLASSES = frozenset(
    {
        "control_interaction",
        "implementation",
        "semantic_behavior",
        "runtime_effect",
        "persistence",
        "recovery",
        "installed_host",
        "external_authority",
        "feature_non_applicability",
    }
)
AUTHORITY_CLASSES = frozenset({"contained", "installed_host", "external_authority"})
REQUIREMENTS_SCHEMA = "px.feature-acceptance-requirements/1.0"
ACCEPTANCE_SCHEMA = "px.feature-acceptance/1.0"


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    evidence_id: str
    evidence_type: str
    claim_type: str
    subject_id: str
    source_revision: str
    authority_class: str
    scope: tuple[str, ...]
    valid_from: str
    expires_at: str | None
    sufficient_alone: bool
    producer: str
    payload_sha256: str


def load_evidence_type_policy(root: Path) -> dict[str, object]:
    value = json.loads(
        (root.resolve() / "registry/evidence_type_policy.json").read_text(encoding="utf-8")
    )
    if not isinstance(value, dict) or value.get("schema_version") != "px.evidence-type-policy/1.0":
        raise ValueError("evidence type policy schema is invalid")
    records = value.get("evidence_types")
    if not isinstance(records, list) or not records:
        raise ValueError("evidence type policy has no records")
    ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("evidence type policy record must be an object")
        evidence_type = str(record.get("evidence_type") or "")
        claims = record.get("allowed_claim_types")
        if not evidence_type or evidence_type in ids:
            raise ValueError("evidence type IDs must be non-empty and unique")
        ids.add(evidence_type)
        if not isinstance(claims, list) or not claims or any(not isinstance(item, str) or not item for item in claims):
            raise ValueError(f"{evidence_type} allowed claim types are invalid")
    if value.get("evidence_type_count") != len(records):
        raise ValueError("evidence type count mismatch")
    return value


def evidence_type_compatible(root: Path, evidence_type: str, claim_type: str) -> bool:
    policy = load_evidence_type_policy(root)
    matches = [
        row for row in policy["evidence_types"]
        if row["evidence_type"] == evidence_type
    ]
    return len(matches) == 1 and claim_type in matches[0]["allowed_claim_types"]


@dataclass(frozen=True)
class FeatureAcceptanceDecision:
    """Result of comparing one acceptance record with its declared requirements."""

    verified: bool
    status: str
    reasons: tuple[str, ...]
    criterion_status: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "verified": self.verified,
            "status": self.status,
            "reasons": list(self.reasons),
            "criteria": [
                {"criterion_id": criterion_id, "status": status}
                for criterion_id, status in self.criterion_status
            ],
        }


def _revision(value: object, field: str) -> str:
    result = str(value or "").strip().lower()
    if not REVISIONS.fullmatch(result):
        raise ValueError(f"{field} must be a 40- or 64-character lowercase hex revision")
    return result


def _revision_map(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    result: dict[str, str] = {}
    for key, revision in value.items():
        name = str(key or "").strip()
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{field} contains an invalid dependency ID")
        result[name] = _revision(revision, f"{field}.{name}")
    return dict(sorted(result.items()))


def _strings(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{field} must be {'an' if allow_empty else 'a non-empty'} array")
    result = [str(item or "").strip() for item in value]
    if any(not item for item in result) or len(result) != len(set(result)):
        raise ValueError(f"{field} entries must be non-empty and unique")
    return result


def _evidence(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must contain evidence")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} entries must be objects")
        reference = str(item.get("reference") or "").strip()
        claim = str(item.get("claim") or "").strip()
        if not reference or not claim:
            raise ValueError(f"{field} entries require reference and claim")
        row: dict[str, object] = {"reference": reference, "claim": claim}
        artifact_sha256 = str(item.get("artifact_sha256") or "").strip().lower()
        if artifact_sha256:
            if not re.fullmatch(r"[a-f0-9]{64}", artifact_sha256):
                raise ValueError(f"{field} artifact_sha256 is invalid")
            row["artifact_sha256"] = artifact_sha256
            if "artifact_size" in item:
                size = item["artifact_size"]
                if not isinstance(size, int) or size < 0:
                    raise ValueError(f"{field} artifact_size is invalid")
                row["artifact_size"] = size
        result.append(row)
    return result


def validate_feature_acceptance_requirements(value: object) -> dict[str, object]:
    """Validate the immutable semantic acceptance contract for one feature."""

    if not isinstance(value, Mapping) or value.get("schema_version") != REQUIREMENTS_SCHEMA:
        raise ValueError("feature acceptance requirements schema is invalid")
    criteria = value.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("feature acceptance requirements need at least one criterion")
    normalized: list[dict[str, object]] = []
    identities: set[str] = set()
    for item in criteria:
        if not isinstance(item, Mapping):
            raise ValueError("feature acceptance criteria must be objects")
        criterion_id = str(item.get("criterion_id") or "").strip()
        if not IDENTIFIER.fullmatch(criterion_id) or criterion_id in identities:
            raise ValueError("feature acceptance criterion IDs must be valid and unique")
        identities.add(criterion_id)
        evidence_classes = _strings(
            item.get("required_evidence_classes"),
            f"acceptance criterion {criterion_id} required_evidence_classes",
        )
        unknown = sorted(set(evidence_classes) - EVIDENCE_CLASSES)
        if unknown:
            raise ValueError(
                f"acceptance criterion {criterion_id} has unknown evidence classes: {unknown}"
            )
        authority = str(item.get("required_authority_class") or "").strip()
        if authority not in AUTHORITY_CLASSES:
            raise ValueError(
                f"acceptance criterion {criterion_id} authority class is invalid"
            )
        normalized.append(
            {
                "criterion_id": criterion_id,
                "required_evidence_classes": evidence_classes,
                "required_authority_class": authority,
                "required_tests": _strings(
                    item.get("required_tests", []),
                    f"acceptance criterion {criterion_id} required_tests",
                    allow_empty=True,
                ),
                "allow_not_applicable": item.get("allow_not_applicable") is True,
            }
        )
    return {
        "schema_version": REQUIREMENTS_SCHEMA,
        "source_revision": _revision(value.get("source_revision"), "source_revision"),
        "dependency_revisions": _revision_map(
            value.get("dependency_revisions", {}), "dependency_revisions"
        ),
        "criteria": normalized,
    }


def validate_feature_acceptance(value: object) -> dict[str, object]:
    """Validate one observed feature-acceptance record without trusting it yet."""

    if not isinstance(value, Mapping) or value.get("schema_version") != ACCEPTANCE_SCHEMA:
        raise ValueError("feature acceptance schema is invalid")
    criteria = value.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("feature acceptance needs at least one criterion result")
    normalized: list[dict[str, object]] = []
    identities: set[str] = set()
    for item in criteria:
        if not isinstance(item, Mapping):
            raise ValueError("feature acceptance criterion results must be objects")
        criterion_id = str(item.get("criterion_id") or "").strip()
        if not IDENTIFIER.fullmatch(criterion_id) or criterion_id in identities:
            raise ValueError("feature acceptance result IDs must be valid and unique")
        identities.add(criterion_id)
        status = str(item.get("status") or "").strip()
        if status not in {"verified", "not_applicable"}:
            raise ValueError(f"feature acceptance criterion {criterion_id} status is invalid")
        evidence_classes = _strings(
            item.get("evidence_classes"),
            f"feature acceptance criterion {criterion_id} evidence_classes",
        )
        unknown = sorted(set(evidence_classes) - EVIDENCE_CLASSES)
        if unknown:
            raise ValueError(
                f"feature acceptance criterion {criterion_id} has unknown evidence classes: {unknown}"
            )
        authority = str(item.get("authority_class") or "").strip()
        if authority not in AUTHORITY_CLASSES:
            raise ValueError(
                f"feature acceptance criterion {criterion_id} authority class is invalid"
            )
        normalized.append(
            {
                "criterion_id": criterion_id,
                "status": status,
                "evidence_classes": evidence_classes,
                "authority_class": authority,
                "tests_run": _strings(
                    item.get("tests_run", []),
                    f"feature acceptance criterion {criterion_id} tests_run",
                    allow_empty=True,
                ),
                "evidence": _evidence(
                    item.get("evidence"),
                    f"feature acceptance criterion {criterion_id} evidence",
                ),
            }
        )
    return {
        "schema_version": ACCEPTANCE_SCHEMA,
        "source_revision": _revision(value.get("source_revision"), "source_revision"),
        "dependency_revisions": _revision_map(
            value.get("dependency_revisions", {}), "dependency_revisions"
        ),
        "criteria": normalized,
    }


def evaluate_feature_acceptance(
    requirements: object, acceptance: object
) -> FeatureAcceptanceDecision:
    """Require exact, current, criterion-level semantic evidence for a feature."""

    try:
        required = validate_feature_acceptance_requirements(requirements)
        observed = validate_feature_acceptance(acceptance)
    except ValueError as error:
        return FeatureAcceptanceDecision(False, "unverified", (str(error),), ())
    reasons: list[str] = []
    if observed["source_revision"] != required["source_revision"]:
        reasons.append("feature_acceptance_source_revision_stale")
    if observed["dependency_revisions"] != required["dependency_revisions"]:
        reasons.append("feature_acceptance_dependency_revision_stale")
    required_by_id = {
        str(item["criterion_id"]): item for item in required["criteria"]  # type: ignore[index]
    }
    observed_by_id = {
        str(item["criterion_id"]): item for item in observed["criteria"]  # type: ignore[index]
    }
    missing = sorted(set(required_by_id) - set(observed_by_id))
    extra = sorted(set(observed_by_id) - set(required_by_id))
    reasons.extend(f"feature_acceptance_missing_criterion:{item}" for item in missing)
    reasons.extend(f"feature_acceptance_unknown_criterion:{item}" for item in extra)
    statuses: list[tuple[str, str]] = []
    for criterion_id, criterion in required_by_id.items():
        result = observed_by_id.get(criterion_id)
        status = str(result.get("status") or "missing") if result else "missing"
        statuses.append((criterion_id, status))
        if result is None:
            continue
        if status == "not_applicable":
            if not criterion["allow_not_applicable"]:
                reasons.append(f"feature_acceptance_not_applicable_forbidden:{criterion_id}")
            if "feature_non_applicability" not in result["evidence_classes"]:
                reasons.append(
                    f"feature_acceptance_not_applicable_evidence_missing:{criterion_id}"
                )
        missing_classes = sorted(
            set(criterion["required_evidence_classes"])
            - set(result["evidence_classes"])
        )
        if missing_classes and status != "not_applicable":
            reasons.append(
                f"feature_acceptance_evidence_class_missing:{criterion_id}:{','.join(missing_classes)}"
            )
        if result["authority_class"] != criterion["required_authority_class"]:
            reasons.append(f"feature_acceptance_authority_mismatch:{criterion_id}")
        missing_tests = sorted(
            set(criterion["required_tests"]) - set(result["tests_run"])
        )
        if missing_tests:
            reasons.append(
                f"feature_acceptance_required_test_missing:{criterion_id}:{','.join(missing_tests)}"
            )
    unique = tuple(sorted(set(reasons)))
    return FeatureAcceptanceDecision(
        not unique,
        "verified" if not unique else (
            "stale" if any("revision_stale" in reason for reason in unique) else "unverified"
        ),
        unique,
        tuple(statuses),
    )


def feature_acceptance_for_card(
    card: Mapping[str, Any], acceptance: object | None = None
) -> FeatureAcceptanceDecision:
    """Evaluate a card, failing closed when it declares runtime needs but no criteria."""

    requirements = card.get("feature_acceptance_requirements")
    runtime_features = card.get("required_runtime_features")
    if requirements is None:
        if isinstance(runtime_features, list) and runtime_features:
            return FeatureAcceptanceDecision(
                False,
                "unverified",
                ("feature_acceptance_requirements_missing_for_runtime_features",),
                (),
            )
        return FeatureAcceptanceDecision(
            False, "undeclared", ("feature_acceptance_requirements_missing",), ()
        )
    selected = card.get("feature_acceptance") if acceptance is None else acceptance
    if selected is None:
        return FeatureAcceptanceDecision(
            False, "unverified", ("feature_acceptance_evidence_missing",), ()
        )
    return evaluate_feature_acceptance(requirements, selected)
