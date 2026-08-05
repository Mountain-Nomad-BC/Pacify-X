"""Clean-room contracts derived from behavior requirements, never source code.

Every function is deterministic and read-only.  The module compares supplied
metadata; it does not import external implementations, contact services, load
models, mutate datasets, or activate a runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SHA256 = re.compile(r"^[0-9a-f]{64}$")
KNOWN_SPLITS = {"train", "validation", "test"}
KNOWN_SURFACE_CHECKS = {
    "config",
    "static",
    "unit",
    "integration",
    "contract",
    "build",
    "health",
    "logs",
    "route",
    "interaction",
    "accessibility",
    "rollback",
}


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ContractSurface:
    contract_id: str
    owner: str
    method: str
    route: str
    fields: Mapping[str, str]
    required_fields: tuple[str, ...]
    authorization_scopes: tuple[str, ...] = ()
    version: str = "1"


def compare_contract_surfaces(
    providers: Iterable[ContractSurface],
    consumers: Iterable[ContractSurface],
) -> dict[str, object]:
    """Compare provider/consumer shapes, ownership, routes, and permissions."""
    provider_values = tuple(providers)
    consumer_values = tuple(consumers)
    provider_ids = [item.contract_id for item in provider_values]
    consumer_ids = [item.contract_id for item in consumer_values]
    if len(provider_ids) != len(set(provider_ids)) or len(consumer_ids) != len(
        set(consumer_ids)
    ):
        raise ValueError("contract IDs must be unique within each side")
    provider_map = {item.contract_id: item for item in provider_values}
    findings: list[dict[str, object]] = []
    for consumer in consumer_values:
        provider = provider_map.get(consumer.contract_id)
        if provider is None:
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "provider_missing",
                    "severity": "high",
                }
            )
            continue
        if not provider.owner.strip():
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "canonical_owner_missing",
                    "severity": "high",
                }
            )
        for field, left, right in (
            ("method", provider.method.upper(), consumer.method.upper()),
            ("route", provider.route, consumer.route),
            ("version", provider.version, consumer.version),
        ):
            if left != right:
                findings.append(
                    {
                        "contract_id": consumer.contract_id,
                        "kind": f"{field}_mismatch",
                        "severity": "high",
                        "provider": left,
                        "consumer": right,
                    }
                )
        missing = sorted(set(consumer.required_fields) - set(provider.fields))
        for field in missing:
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "required_field_missing",
                    "field": field,
                    "severity": "high",
                }
            )
        for field in sorted(set(consumer.required_fields) & set(provider.fields)):
            expected = consumer.fields.get(field)
            actual = provider.fields.get(field)
            if expected and actual != expected:
                findings.append(
                    {
                        "contract_id": consumer.contract_id,
                        "kind": "field_type_mismatch",
                        "field": field,
                        "provider": actual,
                        "consumer": expected,
                        "severity": "high",
                    }
                )
        provider_scopes = set(provider.authorization_scopes)
        consumer_scopes = set(consumer.authorization_scopes)
        for scope in sorted(consumer_scopes - provider_scopes):
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "provider_scope_missing",
                    "scope": scope,
                    "severity": "high",
                }
            )
        for scope in sorted(provider_scopes - consumer_scopes):
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "consumer_scope_unmodeled",
                    "scope": scope,
                    "severity": "medium",
                }
            )
    unconsumed = tuple(sorted(set(provider_ids) - set(consumer_ids)))
    return {
        "decision": "compatible" if not findings else "incompatible",
        "findings": tuple(findings),
        "unconsumed_provider_contracts": unconsumed,
        "provider_sha256": _stable([asdict(item) for item in provider_values]),
        "consumer_sha256": _stable([asdict(item) for item in consumer_values]),
        "source_code_executed": False,
    }


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    case_id: str
    relevant_ids: tuple[str, ...]
    forbidden_ids: tuple[str, ...] = ()


def evaluate_retrieval_readiness(
    cases: Iterable[RetrievalCase],
    ranked_results: Mapping[str, Sequence[str]],
    *,
    k: int = 5,
    minimum_recall: float = 0.8,
    minimum_mrr: float = 0.7,
    minimum_coverage: float = 1.0,
) -> dict[str, object]:
    """Evaluate synthetic/approved retrieval cases and fail closed on leakage."""
    if k < 1 or not all(
        0 <= value <= 1 for value in (minimum_recall, minimum_mrr, minimum_coverage)
    ):
        raise ValueError("retrieval bounds are invalid")
    values = tuple(cases)
    if not values or len({case.case_id for case in values}) != len(values):
        raise ValueError("retrieval cases must be non-empty with unique IDs")
    rows = []
    reasons = []
    recalls = []
    reciprocal_ranks = []
    covered = 0
    forbidden_exposures = []
    for case in values:
        relevant = set(case.relevant_ids)
        if not relevant:
            reasons.append(f"relevance_judgment_missing:{case.case_id}")
        result = tuple(map(str, ranked_results.get(case.case_id, ())))[:k]
        if result:
            covered += 1
        if len(result) != len(set(result)):
            reasons.append(f"duplicate_result_ids:{case.case_id}")
        hits = [index for index, item in enumerate(result, 1) if item in relevant]
        recall = len(set(result) & relevant) / max(1, len(relevant))
        reciprocal_rank = 1 / hits[0] if hits else 0.0
        exposed = tuple(sorted(set(result) & set(case.forbidden_ids)))
        if exposed:
            forbidden_exposures.append({"case_id": case.case_id, "ids": exposed})
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        rows.append(
            {
                "case_id": case.case_id,
                "returned": len(result),
                "recall_at_k": round(recall, 6),
                "reciprocal_rank": round(reciprocal_rank, 6),
                "forbidden_exposure": exposed,
            }
        )
    metrics = {
        "cases": len(values),
        "k": k,
        "coverage": round(covered / len(values), 6),
        "mean_recall_at_k": round(sum(recalls) / len(recalls), 6),
        "mean_reciprocal_rank": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 6),
        "forbidden_exposure_count": sum(
            len(item["ids"]) for item in forbidden_exposures
        ),
    }
    if metrics["coverage"] < minimum_coverage:
        reasons.append("coverage_below_threshold")
    if metrics["mean_recall_at_k"] < minimum_recall:
        reasons.append("recall_below_threshold")
    if metrics["mean_reciprocal_rank"] < minimum_mrr:
        reasons.append("mrr_below_threshold")
    if forbidden_exposures:
        reasons.append("forbidden_result_exposed")
    reasons = sorted(set(reasons))
    return {
        "decision": "ready" if not reasons else "blocked",
        "activation_allowed": not reasons,
        "reasons": tuple(reasons),
        "metrics": metrics,
        "cases": tuple(rows),
        "forbidden_exposures": tuple(forbidden_exposures),
        "evaluation_sha256": _stable({"cases": rows, "metrics": metrics}),
    }


@dataclass(frozen=True, slots=True)
class TrainingRecord:
    record_id: str
    content_sha256: str
    source_id: str
    license: str
    consent: str
    label: str
    split: str
    subject_id: str | None = None
    contains_sensitive_data: bool = False
    approved_sensitive_use: bool = False


def gate_model_dataset(
    records: Iterable[TrainingRecord],
    *,
    allowed_licenses: Iterable[str],
    minimum_records: int = 2,
) -> dict[str, object]:
    """Gate model metadata for provenance, rights, split leakage, and privacy."""
    values = tuple(records)
    allowed = {item.casefold().strip() for item in allowed_licenses if item.strip()}
    reasons = []
    if len(values) < minimum_records:
        reasons.append("minimum_record_count_not_met")
    ids = [item.record_id for item in values]
    if len(ids) != len(set(ids)):
        reasons.append("record_id_duplicate")
    content_splits: dict[str, set[str]] = {}
    subject_splits: dict[str, set[str]] = {}
    label_splits: dict[str, set[str]] = {}
    for item in values:
        if not item.record_id or not item.source_id:
            reasons.append("record_identity_missing")
        if not SHA256.fullmatch(item.content_sha256):
            reasons.append(f"content_hash_invalid:{item.record_id}")
        if item.license.casefold().strip() not in allowed:
            reasons.append(f"license_not_allowed:{item.record_id}")
        if not item.consent.strip():
            reasons.append(f"consent_or_authority_missing:{item.record_id}")
        if not item.label.strip():
            reasons.append(f"label_missing:{item.record_id}")
        if item.split not in KNOWN_SPLITS:
            reasons.append(f"split_invalid:{item.record_id}")
        if item.contains_sensitive_data and not item.approved_sensitive_use:
            reasons.append(f"sensitive_use_not_approved:{item.record_id}")
        content_splits.setdefault(item.content_sha256, set()).add(item.split)
        if item.subject_id:
            subject_splits.setdefault(item.subject_id, set()).add(item.split)
        label_splits.setdefault(item.label, set()).add(item.split)
    for digest, splits in sorted(content_splits.items()):
        if len(splits) > 1:
            reasons.append(f"content_split_leakage:{digest[:12]}")
    for subject, splits in sorted(subject_splits.items()):
        if len(splits) > 1:
            reasons.append(f"subject_split_leakage:{subject}")
    reasons = sorted(set(reasons))
    split_counts = {
        split: sum(item.split == split for item in values)
        for split in sorted(KNOWN_SPLITS)
    }
    return {
        "decision": "admitted_metadata" if not reasons else "blocked",
        "training_or_model_load_performed": False,
        "reasons": tuple(reasons),
        "record_count": len(values),
        "split_counts": split_counts,
        "label_split_coverage": {
            label: tuple(sorted(splits))
            for label, splits in sorted(label_splits.items())
        },
        "dataset_sha256": _stable([asdict(item) for item in values]),
    }


def evaluate_numeric_shift(
    baseline: Sequence[float],
    observed: Sequence[float],
    *,
    threshold: float = 0.25,
) -> dict[str, object]:
    """Robustly assess mean shift, including empty, constant, and non-finite data."""
    if threshold < 0:
        raise ValueError("shift threshold cannot be negative")
    left = tuple(map(float, baseline))
    right = tuple(map(float, observed))
    errors = []
    if not left or not right:
        errors.append("series_empty")
    if any(not math.isfinite(value) for value in (*left, *right)):
        errors.append("non_finite_value")
    score = 1.0
    if not errors:
        left_mean = sum(left) / len(left)
        right_mean = sum(right) / len(right)
        variance = sum((value - left_mean) ** 2 for value in left) / len(left)
        if variance == 0:
            score = (
                0.0
                if right_mean == left_mean
                and all(value == left_mean for value in right)
                else 1.0
            )
        else:
            score = abs(right_mean - left_mean) / math.sqrt(variance)
    drifted = bool(errors) or score > threshold
    return {
        "decision": "drifted" if drifted else "within_threshold",
        "score": round(score, 6),
        "threshold": threshold,
        "errors": tuple(errors),
    }


def validate_dimension_steps(
    steps: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Check declared dimensional algebra without evaluating an expression."""
    findings = []
    normalized = []
    for index, raw in enumerate(steps):
        operation = str(raw.get("operation", ""))
        left = {
            str(key): int(value)
            for key, value in dict(raw.get("left", {})).items()
            if int(value)
        }
        right = {
            str(key): int(value)
            for key, value in dict(raw.get("right", {})).items()
            if int(value)
        }
        result = {
            str(key): int(value)
            for key, value in dict(raw.get("result", {})).items()
            if int(value)
        }
        if operation in {"add", "subtract"}:
            valid = left == right == result
        elif operation in {"multiply", "divide"}:
            sign = 1 if operation == "multiply" else -1
            expected = {
                dimension: left.get(dimension, 0) + sign * right.get(dimension, 0)
                for dimension in set(left) | set(right)
            }
            expected = {key: value for key, value in expected.items() if value}
            valid = expected == result
        else:
            valid = False
        normalized.append(
            {"operation": operation, "left": left, "right": right, "result": result}
        )
        if not valid:
            findings.append(
                {"step": index, "kind": "dimension_mismatch_or_unknown_operation"}
            )
    return {
        "decision": "valid" if normalized and not findings else "invalid",
        "findings": tuple(findings),
        "steps_sha256": _stable(normalized),
    }


def plan_runtime_surface_validation(
    surfaces: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Order static-to-live validation and expose every approval boundary."""
    phases = (
        "config",
        "static",
        "unit",
        "integration",
        "contract",
        "build",
        "health",
        "logs",
        "route",
        "interaction",
        "accessibility",
        "rollback",
    )
    values = tuple(surfaces)
    errors = []
    planned = []
    for surface in values:
        surface_id = str(surface.get("id", "")).strip()
        owner = str(surface.get("owner", "")).strip()
        checks = tuple(dict.fromkeys(map(str, surface.get("checks", ()))))
        unknown = sorted(set(checks) - KNOWN_SURFACE_CHECKS)
        if not surface_id or not owner:
            errors.append(
                f"surface_identity_or_owner_missing:{surface_id or 'unknown'}"
            )
        if unknown:
            errors.append(f"unknown_checks:{surface_id}:{','.join(unknown)}")
        ordered = tuple(phase for phase in phases if phase in checks)
        planned.append(
            {
                "id": surface_id,
                "owner": owner,
                "checks": ordered,
                "live_runtime_required": bool(
                    set(ordered)
                    & {"health", "logs", "route", "interaction", "accessibility"}
                ),
                "approval_required": bool(surface.get("mutating"))
                or "build" in ordered,
            }
        )
    return {
        "decision": "planned" if values and not errors else "blocked",
        "errors": tuple(sorted(errors)),
        "surfaces": tuple(planned),
        "execution_performed": False,
        "plan_sha256": _stable(planned),
    }
