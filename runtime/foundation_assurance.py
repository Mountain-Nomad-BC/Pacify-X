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
import time
from fractions import Fraction
from .numeric_inputs import (
    bounded_text,
    bounded_sequence,
    bounded_mapping,
    bounded_json_value,
    bounded_items,
    bounded_integer,
    finite_number,
)
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


def _check_time(deadline):
    if time.monotonic() >= deadline:
        raise ValueError("foundation input exceeded its cooperative duration budget")


def _text(value, name, *, maximum=512, empty=False):
    if type(value) is not str:
        raise ValueError(name + " must be actual text")
    if empty and not value:
        return value
    bounded_text(value, name, maximum=maximum, strip=False)
    if not value.strip():
        raise ValueError(name + " must not be whitespace only")
    return value


def _labels(value, name, *, maximum=256, unique=True):
    bounded_sequence(value, name, maximum=maximum)
    result = tuple(_text(item, name) for item in value)
    if unique and len(result) != len(set(result)):
        raise ValueError(name + " must not contain duplicates")
    return result


def _frame(value, deadline):
    # All callers validate their flat dataclass/record fields first. Tuple-to-list
    # conversion is only a JSON admission view; hash framing stays with _stable.
    _check_time(deadline)

    def convert(item):
        if type(item) in (list, tuple, _Rows):
            return [convert(child) for child in item]
        if type(item) is dict:
            return {key: convert(child) for key, child in item.items()}
        return item

    normalized = convert(value)
    bounded_json_value(normalized)
    _check_time(deadline)
    return normalized


def _values(values, name, *, maximum, deadline):
    _check_time(deadline)
    if type(values) in (str, bytes, bytearray):
        raise ValueError(name + " requires a collection, not scalar text or bytes")
    if type(values) in (list, tuple) and len(values) > maximum:
        raise ValueError(name + " exceeds its item budget")
    return tuple(
        bounded_items(
            values,
            name,
            maximum=maximum,
            max_seconds=min(60.0, deadline - time.monotonic()),
        )
    )


def _contract_values(values, name, deadline, budget):
    result = _values(values, name, maximum=10000, deadline=deadline)
    for item in result:
        _check_time(deadline)
        if type(item) is not ContractSurface:
            raise ValueError(name + " requires actual ContractSurface values")
        for field in ("contract_id", "owner", "method", "version"):
            _text(getattr(item, field), name + " " + field)
        _text(item.route, name + " route", maximum=4096)
        bounded_mapping(item.fields, name + " fields", maximum=256)
        for key, value in item.fields.items():
            _text(key, "field name")
            _text(value, "field type")
        required = _labels(item.required_fields, name + " required fields")
        if not set(required) <= set(item.fields):
            raise ValueError(name + " requires a field absent from its own declaration")
        _labels(item.authorization_scopes, name + " scopes")
        budget.add(asdict(item))
    return result


def _retrieval_values(cases, ranked_results, deadline):
    budget = _Budget(deadline)
    values = _values(cases, "retrieval cases", maximum=10000, deadline=deadline)
    for item in values:
        if type(item) is not RetrievalCase:
            raise ValueError("retrieval cases require actual RetrievalCase values")
        _text(item.case_id, "case identity")
        relevant = _labels(item.relevant_ids, "relevant IDs", maximum=10000)
        forbidden = _labels(item.forbidden_ids, "forbidden IDs", maximum=10000)
        if set(relevant) & set(forbidden):
            raise ValueError(
                "retrieval judgments cannot be both relevant and forbidden"
            )
        budget.add(asdict(item))
    bounded_mapping(ranked_results, "ranked results", maximum=10000)
    for key, ids in ranked_results.items():
        _text(key, "ranked case identity")
        _labels(ids, "ranked IDs", maximum=10000, unique=False)
        budget.add({key: ids})
    return values


def _training_values(records, allowed_licenses, deadline):
    budget = _Budget(deadline)
    values = _values(records, "training records", maximum=10000, deadline=deadline)
    licenses = _values(
        allowed_licenses, "allowed licenses", maximum=128, deadline=deadline
    )
    for license_name in licenses:
        _text(license_name, "allowed license")
        budget.add(license_name)
    if len({name.casefold().strip() for name in licenses}) != len(licenses):
        raise ValueError("allowed licenses must be unique")
    for item in values:
        _check_time(deadline)
        if type(item) is not TrainingRecord:
            raise ValueError("training records require actual TrainingRecord values")
        for field in (
            "record_id",
            "content_sha256",
            "source_id",
            "license",
            "consent",
            "label",
            "split",
        ):
            _text(getattr(item, field), "training " + field, empty=True)
        if item.subject_id is not None:
            _text(item.subject_id, "subject identity")
        if (
            type(item.contains_sensitive_data) is not bool
            or type(item.approved_sensitive_use) is not bool
        ):
            raise ValueError("sensitive-data flags must be actual booleans")
        budget.add(asdict(item))
    return values, licenses


def _dimension(value, name):
    bounded_mapping(value, name, maximum=64)
    for key, exponent in value.items():
        _text(key, "dimension identity")
        bounded_integer(exponent, "dimension exponent", minimum=-1024, maximum=1024)
    return {key: exponent for key, exponent in value.items() if exponent}


class _Budget:
    """One local input/output byte counter; never an authority or persistent cache."""

    def __init__(self, deadline):
        self.deadline = deadline
        self.used = 0

    def add(self, value):
        normalized = _frame(value, self.deadline)
        # The shared codec bounds each ASCII image before serialization. Each
        # flat row is charged before expansion of the following row.
        size = (
            len(
                json.dumps(
                    normalized,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            + 16
        )
        if self.used + size > 8 * 1024 * 1024:
            raise ValueError("foundation aggregate byte budget exhausted")
        self.used += size
        _check_time(self.deadline)


class _Rows(list):
    def __init__(self, budget):
        super().__init__()
        self.budget = budget

    def append(self, value):
        self.budget.add(value)
        super().append(value)


def _finish(payload, deadline, hashes=None):
    hashes = hashes or {}
    for key in hashes:
        payload[key] = "0" * 64
    _frame(payload, deadline)
    for key, value in hashes.items():
        _frame(value, deadline)
        payload[key] = _stable(value)
    _check_time(deadline)
    return payload


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
    """Compare provider output guarantees against consumer input requirements.

    Owners identify distinct supplied service/client roles; they need not match.
    This is declared shape compatibility, not request-direction inference,
    authenticated ownership, execution permission or runtime interaction proof.
    """
    deadline = time.monotonic() + 60.0
    input_budget = _Budget(deadline)
    provider_values = _contract_values(
        providers, "provider contracts", deadline, input_budget
    )
    consumer_values = _contract_values(
        consumers, "consumer contracts", deadline, input_budget
    )
    if not provider_values or not consumer_values:
        raise ValueError(
            "contract comparison requires nonempty provider and consumer sides"
        )
    _frame(
        {
            "providers": [asdict(item) for item in provider_values],
            "consumers": [asdict(item) for item in consumer_values],
        },
        deadline,
    )
    provider_ids = [item.contract_id for item in provider_values]
    consumer_ids = [item.contract_id for item in consumer_values]
    if len(provider_ids) != len(set(provider_ids)) or len(consumer_ids) != len(
        set(consumer_ids)
    ):
        raise ValueError("contract IDs must be unique within each side")
    provider_map = {item.contract_id: item for item in provider_values}
    findings: list[dict[str, object]] = _Rows(_Budget(deadline))
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
        for field in sorted(
            (set(consumer.required_fields) & set(provider.fields))
            - set(provider.required_fields)
        ):
            findings.append(
                {
                    "contract_id": consumer.contract_id,
                    "kind": "required_field_not_guaranteed",
                    "field": field,
                    "severity": "high",
                }
            )
        for field in sorted(set(consumer.fields) & set(provider.fields)):
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
    _check_time(deadline)
    unconsumed = tuple(sorted(set(provider_ids) - set(consumer_ids)))
    return _finish(
        {
            "decision": "compatible" if not findings else "incompatible",
            "findings": tuple(findings),
            "unconsumed_provider_contracts": unconsumed,
            "compatibility_direction": "provider_output_to_consumer_input",
            "provider_sha256": None,
            "consumer_sha256": None,
            "source_code_executed": False,
        },
        deadline,
        {
            "provider_sha256": [asdict(item) for item in provider_values],
            "consumer_sha256": [asdict(item) for item in consumer_values],
        },
    )


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
    deadline = time.monotonic() + 60.0
    k = bounded_integer(k, "retrieval k", maximum=1000)
    minimum_recall = finite_number(
        minimum_recall, "minimum recall", minimum=0, maximum=1
    )
    minimum_mrr = finite_number(minimum_mrr, "minimum MRR", minimum=0, maximum=1)
    minimum_coverage = finite_number(
        minimum_coverage, "minimum coverage", minimum=0, maximum=1
    )
    values = _retrieval_values(cases, ranked_results, deadline)
    if not values or len({case.case_id for case in values}) != len(values):
        raise ValueError("retrieval cases must be non-empty with unique IDs")
    output_budget = _Budget(deadline)
    rows = _Rows(output_budget)
    reasons = _Rows(output_budget)
    recalls = []
    reciprocal_ranks = []
    covered = 0
    forbidden_exposures = _Rows(output_budget)
    for case in values:
        relevant = set(case.relevant_ids)
        if not relevant:
            reasons.append(f"relevance_judgment_missing:{case.case_id}")
        result = tuple(ranked_results.get(case.case_id, ())[:k])
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
    _check_time(deadline)
    coverage = covered / len(values)
    mean_recall = math.fsum(recalls) / len(recalls)
    mean_reciprocal_rank = math.fsum(reciprocal_ranks) / len(reciprocal_ranks)
    metrics = {
        "cases": len(values),
        "k": k,
        "coverage": round(coverage, 6),
        "mean_recall_at_k": round(mean_recall, 6),
        "mean_reciprocal_rank": round(mean_reciprocal_rank, 6),
        "forbidden_exposure_count": sum(
            len(item["ids"]) for item in forbidden_exposures
        ),
    }
    if coverage < minimum_coverage:
        reasons.append("coverage_below_threshold")
    if mean_recall < minimum_recall:
        reasons.append("recall_below_threshold")
    if mean_reciprocal_rank < minimum_mrr:
        reasons.append("mrr_below_threshold")
    if forbidden_exposures:
        reasons.append("forbidden_result_exposed")
    reasons = sorted(set(reasons))
    return _finish(
        {
            "decision": "ready" if not reasons else "blocked",
            "activation_allowed": not reasons,
            "reasons": tuple(reasons),
            "metrics": metrics,
            "cases": tuple(rows),
            "forbidden_exposures": tuple(forbidden_exposures),
            "evaluation_sha256": None,
        },
        deadline,
        {"evaluation_sha256": {"cases": rows, "metrics": metrics}},
    )


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
    deadline = time.monotonic() + 60.0
    minimum_records = bounded_integer(
        minimum_records, "minimum training records", maximum=10000
    )
    values, licenses = _training_values(records, allowed_licenses, deadline)
    allowed = {item.casefold().strip() for item in licenses}
    reasons = _Rows(_Budget(deadline))
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
    _check_time(deadline)
    split_counts = {
        split: sum(item.split == split for item in values)
        for split in sorted(KNOWN_SPLITS)
    }
    return _finish(
        {
            "decision": "admitted_metadata" if not reasons else "blocked",
            "training_or_model_load_performed": False,
            "reasons": tuple(reasons),
            "record_count": len(values),
            "split_counts": split_counts,
            "label_split_coverage": {
                label: tuple(sorted(splits))
                for label, splits in sorted(label_splits.items())
            },
            "dataset_sha256": None,
        },
        deadline,
        {"dataset_sha256": [asdict(item) for item in values]},
    )


def evaluate_numeric_shift(
    baseline: Sequence[float],
    observed: Sequence[float],
    *,
    threshold: float = 0.25,
) -> dict[str, object]:
    """Assess standardized mean shift, not distribution equivalence.

    Constant baselines retain the established zero/one score convention. Invalid
    series or an unrepresentable standardized score fail closed explicitly.
    """
    deadline = time.monotonic() + 60.0
    threshold = finite_number(threshold, "shift threshold", minimum=0)
    input_budget = _Budget(deadline)
    left = _values(baseline, "baseline series", maximum=100000, deadline=deadline)
    right = _values(observed, "observed series", maximum=100000, deadline=deadline)

    def numbers(values):
        result = []
        for value in values:
            _check_time(deadline)
            if type(value) not in (int, float):
                raise ValueError("shift series requires actual numbers")
            if type(value) is float and not math.isfinite(value):
                input_budget.add(None)  # Charge one invalid scalar; diagnose below.
                result.append(value)
            else:
                number = finite_number(value, "shift value")
                input_budget.add(value)
                result.append(number)
        return tuple(result)

    left, right = numbers(left), numbers(right)
    errors = []
    if not left or not right:
        errors.append("series_empty")
    if any(not math.isfinite(value) for values in (left, right) for value in values):
        errors.append("non_finite_value")
    score = 1.0
    if not errors:
        if all(value == left[0] for value in left):
            score = 0.0 if all(value == left[0] for value in right) else 1.0
        else:
            left_scale = max(abs(value) for value in left)

            def scaled_mean(values):
                total = Fraction(0)
                for value in values:
                    _check_time(deadline)
                    total += Fraction.from_float(value)
                return float(total / len(values) / Fraction.from_float(left_scale))

            left_mean = scaled_mean(left)
            variance = math.fsum(
                (value / left_scale - left_mean) ** 2 for value in left
            ) / len(left)
            if variance <= 0:
                errors.append("numeric_variance_unrepresentable")
            else:
                try:
                    right_mean = scaled_mean(right)
                    score = abs(right_mean - left_mean) / math.sqrt(variance)
                except OverflowError:
                    score = math.inf
                if not math.isfinite(score):
                    errors.append("numeric_score_unrepresentable")
                    score = 1.0
    _check_time(deadline)
    return _finish(
        {
            "decision": "drifted"
            if errors or score > threshold
            else "within_threshold",
            "score": round(score, 6),
            "threshold": threshold,
            "errors": tuple(errors),
        },
        deadline,
    )


def validate_dimension_steps(
    steps: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Check bounded independent dimension declarations without evaluation."""
    deadline = time.monotonic() + 60.0
    values = _values(steps, "dimension steps", maximum=10000, deadline=deadline)
    normalized = _Rows(_Budget(deadline))
    for raw in values:
        _check_time(deadline)
        bounded_mapping(raw, "dimension step", maximum=4)
        if set(raw) != {"operation", "left", "right", "result"}:
            raise ValueError("dimension step fields must be exact")
        normalized.append(
            {
                "operation": _text(raw["operation"], "dimension operation", maximum=32),
                "left": _dimension(raw["left"], "left dimension"),
                "right": _dimension(raw["right"], "right dimension"),
                "result": _dimension(raw["result"], "result dimension"),
            }
        )
    _frame(normalized, deadline)
    findings = _Rows(_Budget(deadline))
    for index, step in enumerate(normalized):
        operation, left, right, result = (
            step[key] for key in ("operation", "left", "right", "result")
        )
        if operation in {"add", "subtract"}:
            valid = left == right == result
        elif operation in {"multiply", "divide"}:
            sign = 1 if operation == "multiply" else -1
            expected = {
                key: left.get(key, 0) + sign * right.get(key, 0)
                for key in set(left) | set(right)
            }
            valid = {key: value for key, value in expected.items() if value} == result
        else:
            valid = False
        if not valid:
            findings.append(
                {"step": index, "kind": "dimension_mismatch_or_unknown_operation"}
            )
    _check_time(deadline)
    return _finish(
        {
            "decision": "valid" if normalized and (not findings) else "invalid",
            "findings": tuple(findings),
            "steps_sha256": None,
        },
        deadline,
        {"steps_sha256": normalized},
    )


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
    deadline = time.monotonic() + 60.0
    input_budget = _Budget(deadline)
    values = _values(surfaces, "runtime surfaces", maximum=10000, deadline=deadline)
    for surface in values:
        bounded_mapping(surface, "runtime surface", maximum=4)
        if not set(surface) <= {"id", "owner", "checks", "mutating"}:
            raise ValueError("unsupported runtime surface fields")
        _text(surface.get("id", ""), "surface identity", empty=True)
        _text(surface.get("owner", ""), "surface owner", empty=True)
        _labels(surface.get("checks", ()), "surface checks", maximum=12, unique=False)
        if type(surface.get("mutating", False)) is not bool:
            raise ValueError("surface mutation flag must be an actual boolean")
        input_budget.add(surface)
    _frame(values, deadline)
    output_budget = _Budget(deadline)
    errors = _Rows(output_budget)
    planned = _Rows(output_budget)
    seen = set()
    for surface in values:
        surface_id = surface.get("id", "").strip()
        owner = surface.get("owner", "").strip()
        checks = tuple(surface.get("checks", ()))
        if surface_id in seen:
            errors.append("surface_identity_duplicate:" + surface_id)
        seen.add(surface_id)
        if not checks:
            errors.append("surface_checks_missing:" + surface_id)
        if len(checks) != len(set(checks)):
            errors.append("surface_checks_duplicate:" + surface_id)
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
    _check_time(deadline)
    return _finish(
        {
            "decision": "planned" if values and (not errors) else "blocked",
            "errors": tuple(sorted(errors)),
            "surfaces": tuple(planned),
            "execution_performed": False,
            "plan_sha256": None,
        },
        deadline,
        {"plan_sha256": planned},
    )
