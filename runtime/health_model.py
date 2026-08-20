"""Canonical, fail-closed health taxonomy and projection model."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .contracts import ContractValidationError, validate_instance


REGISTRY_PATH = Path("registry/health_taxonomy.json")
REGISTRY_SCHEMA = Path("contracts/operations/health-model-registry.schema.json")
REPORT_SCHEMA = Path("contracts/operations/health-report.schema.json")
STATES = ("healthy", "degraded", "blocked", "stale", "unknown")
STATE_PRECEDENCE = ("blocked", "stale", "degraded", "unknown", "healthy")
LIFECYCLE_DIMENSIONS = (
    "configured",
    "detected",
    "connected",
    "authoritative",
    "ready",
)
DOMAINS = (
    "runtime",
    "extension",
    "providers",
    "observers",
    "sensors",
    "coordination",
    "memory",
)
CLAIM_FIELDS = {
    "surface_id",
    "lifecycle",
    "observed_at",
    "last_success",
    "last_failure",
    "degradation",
    "blockers",
    "claimed_state",
    "authority",
}
REASON_CODE = re.compile(r"^[a-z][a-z0-9._-]{1,95}$")


class HealthModelError(ValueError):
    """Raised when health facts or registry claims are contradictory."""


def _parse_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise HealthModelError(f"{field} must be an RFC3339 date-time")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as error:
        raise HealthModelError(f"{field} must be an RFC3339 date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HealthModelError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _evaluation_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        return _parse_datetime(value, "evaluated_at")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HealthModelError("evaluated_at must include a timezone")
    return value.astimezone(timezone.utc)


def _reason_codes(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise HealthModelError(f"{field} must be an array")
    if len(value) != len(set(value)):
        raise HealthModelError(f"{field} must not contain duplicates")
    if any(
        not isinstance(item, str) or REASON_CODE.fullmatch(item) is None
        for item in value
    ):
        raise HealthModelError(f"{field} contains an invalid reason code")
    return list(value)


def _load_registry(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
        validate_instance(payload, root / REGISTRY_SCHEMA)
    except (ContractValidationError, OSError, UnicodeError, ValueError) as error:
        raise HealthModelError(f"invalid canonical health registry: {error}") from error
    if payload["state_precedence"] != list(STATE_PRECEDENCE):
        raise HealthModelError(
            "health state precedence conflicts with runtime authority"
        )
    if payload["lifecycle_dimensions"] != list(LIFECYCLE_DIMENSIONS):
        raise HealthModelError(
            "health lifecycle dimensions conflict with runtime authority"
        )
    if payload["domains"] != list(DOMAINS):
        raise HealthModelError("health domains conflict with runtime authority")
    surfaces = payload["surfaces"]
    identifiers = [item["surface_id"] for item in surfaces]
    surface_domains = [item["domain"] for item in surfaces]
    if len(identifiers) != len(set(identifiers)):
        raise HealthModelError("health registry contains duplicate surface identifiers")
    if len(surfaces) != len(DOMAINS) or set(surface_domains) != set(DOMAINS):
        raise HealthModelError(
            "health registry must own exactly one surface per domain"
        )
    if any("vscode_extension" not in item["projection_consumers"] for item in surfaces):
        raise HealthModelError(
            "every health surface must declare its extension projection"
        )
    if any(
        not item["remediation"]["deep_link"].startswith("px://") for item in surfaces
    ):
        raise HealthModelError("health remediation deep links must use the px scheme")
    return payload


def validate_health_registry(root: Path) -> dict[str, Any]:
    """Return a stable validation result for the canonical health registry."""
    try:
        payload = _load_registry(root.resolve())
    except HealthModelError as error:
        return {
            "schema_version": "px.health-registry-validation/1.0",
            "valid": False,
            "surface_count": 0,
            "domains": [],
            "errors": [str(error)],
        }
    return {
        "schema_version": "px.health-registry-validation/1.0",
        "valid": True,
        "surface_count": len(payload["surfaces"]),
        "domains": list(payload["domains"]),
        "errors": [],
    }


def health_catalog(root: Path) -> dict[str, Any]:
    """Return the schema-validated taxonomy for CLI and read-only projections."""
    payload = _load_registry(root.resolve())
    return {"valid": True, **payload}


def _validate_lifecycle(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != set(LIFECYCLE_DIMENSIONS):
        raise HealthModelError(
            "lifecycle must contain exactly configured, detected, connected, "
            "authoritative, and ready"
        )
    lifecycle = dict(value)
    if any(type(lifecycle[field]) is not bool for field in LIFECYCLE_DIMENSIONS):
        raise HealthModelError("lifecycle values must be booleans")
    if lifecycle["connected"] and not lifecycle["detected"]:
        raise HealthModelError("connected health requires detected=true")
    if lifecycle["authoritative"] and not lifecycle["connected"]:
        raise HealthModelError("authoritative health requires connected=true")
    if lifecycle["ready"] and not all(
        lifecycle[field] for field in LIFECYCLE_DIMENSIONS[:-1]
    ):
        raise HealthModelError("ready health requires every prior lifecycle fact")
    return lifecycle


def _nullable_event_time(
    value: object, field: str, evaluated_at: datetime, observed_at: datetime | None
) -> str | None:
    if value is None:
        return None
    parsed = _parse_datetime(value, field)
    if parsed > evaluated_at:
        raise HealthModelError(f"{field} cannot be in the future")
    if observed_at is not None and parsed > observed_at:
        raise HealthModelError(f"{field} cannot be newer than observed_at")
    return _format_datetime(parsed)


def _last_failure(
    value: object, evaluated_at: datetime, observed_at: datetime | None
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"at", "code"}:
        raise HealthModelError("last_failure must contain exactly at and code")
    code = value["code"]
    if not isinstance(code, str) or REASON_CODE.fullmatch(code) is None:
        raise HealthModelError("last_failure.code is invalid")
    at = _nullable_event_time(value["at"], "last_failure.at", evaluated_at, observed_at)
    assert at is not None
    return {"at": at, "code": code}


def _derive_state(
    lifecycle: Mapping[str, bool],
    *,
    stale: bool,
    last_success: str | None,
    last_failure: Mapping[str, str] | None,
    degradation: Sequence[str],
    blockers: Sequence[str],
) -> str:
    if blockers:
        return "blocked"
    if stale:
        return "stale"
    unresolved_failure = bool(
        last_failure
        and (
            last_success is None
            or _parse_datetime(last_failure["at"], "last_failure.at")
            > _parse_datetime(last_success, "last_success")
        )
    )
    if degradation or unresolved_failure:
        return "degraded"
    if lifecycle["ready"]:
        return "healthy"
    if any(lifecycle.values()) or last_success is not None or last_failure is not None:
        return "degraded"
    return "unknown"


def assess_health_claim(
    root: Path,
    claim: Mapping[str, object],
    *,
    evaluated_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Derive one health record; presentation-provided state cannot override facts."""
    unknown = set(claim) - CLAIM_FIELDS
    required = {
        "surface_id",
        "lifecycle",
        "observed_at",
        "last_success",
        "last_failure",
        "degradation",
        "blockers",
    }
    missing = required - set(claim)
    if unknown or missing:
        raise HealthModelError(
            f"health claim fields conflict: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    registry = _load_registry(root.resolve())
    by_id = {item["surface_id"]: item for item in registry["surfaces"]}
    surface_id = claim["surface_id"]
    if not isinstance(surface_id, str) or surface_id not in by_id:
        raise HealthModelError(f"unknown health surface: {surface_id!r}")
    surface = by_id[surface_id]
    supplied_authority = claim.get("authority")
    if supplied_authority is not None and supplied_authority != surface["authority"]:
        raise HealthModelError("health authority conflicts with canonical registry")

    lifecycle = _validate_lifecycle(claim["lifecycle"])
    evaluation = _evaluation_time(evaluated_at)
    raw_observed = claim["observed_at"]
    observed = (
        None if raw_observed is None else _parse_datetime(raw_observed, "observed_at")
    )
    if observed is not None and observed > evaluation:
        raise HealthModelError("observed_at cannot be in the future")
    degradation = _reason_codes(claim["degradation"], "degradation")
    blockers = _reason_codes(claim["blockers"], "blockers")
    has_facts = any(lifecycle.values()) or bool(
        degradation or blockers or claim["last_success"] or claim["last_failure"]
    )
    if observed is None and has_facts:
        raise HealthModelError("observed_at is required when health facts are present")
    last_success = _nullable_event_time(
        claim["last_success"], "last_success", evaluation, observed
    )
    last_failure = _last_failure(claim["last_failure"], evaluation, observed)
    age = (
        None if observed is None else max(0.0, (evaluation - observed).total_seconds())
    )
    stale = age is not None and age > surface["ttl_seconds"]
    state = _derive_state(
        lifecycle,
        stale=stale,
        last_success=last_success,
        last_failure=last_failure,
        degradation=degradation,
        blockers=blockers,
    )
    claimed_state = claim.get("claimed_state")
    if claimed_state is not None and claimed_state != state:
        raise HealthModelError(
            f"claimed state {claimed_state!r} conflicts with derived state {state!r}"
        )
    return {
        "surface_id": surface_id,
        "domain": surface["domain"],
        "state": state,
        "lifecycle": lifecycle,
        "authority": dict(surface["authority"]),
        "freshness": {
            "observed_at": None if observed is None else _format_datetime(observed),
            "evaluated_at": _format_datetime(evaluation),
            "age_seconds": None if age is None else round(age, 6),
            "ttl_seconds": surface["ttl_seconds"],
            "stale": stale,
        },
        "last_success": last_success,
        "last_failure": last_failure,
        "degradation": degradation,
        "blockers": blockers,
        "remediation": dict(surface["remediation"]),
    }


def assess_health_report(
    root: Path,
    claims: Sequence[Mapping[str, object]],
    *,
    evaluated_at: datetime | str | None = None,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Build and schema-check a deterministic multi-surface health report."""
    root = root.resolve()
    registry = _load_registry(root)
    evaluation = _evaluation_time(evaluated_at)
    if isinstance(claims, (str, bytes)) or not isinstance(claims, Sequence):
        raise HealthModelError("health claims must be a sequence of objects")
    if not all(isinstance(claim, Mapping) for claim in claims):
        raise HealthModelError("health claims must be a sequence of objects")
    surface_ids = [claim.get("surface_id") for claim in claims]
    if any(not isinstance(surface_id, str) for surface_id in surface_ids):
        raise HealthModelError("every health claim requires a string surface_id")
    if len(surface_ids) != len(set(surface_ids)):
        raise HealthModelError("health report contains duplicate surface claims")
    expected = {item["surface_id"] for item in registry["surfaces"]}
    supplied = set(surface_ids)
    if require_complete and supplied != expected:
        raise HealthModelError(
            f"health report coverage mismatch: missing={sorted(expected - supplied)}, "
            f"unexpected={sorted(supplied - expected)}"
        )
    records = [
        assess_health_claim(root, claim, evaluated_at=evaluation) for claim in claims
    ]
    records.sort(key=lambda record: record["surface_id"])
    counts = Counter(record["state"] for record in records)
    overall = next(
        (state for state in STATE_PRECEDENCE if counts[state]),
        "unknown",
    )
    report = {
        "schema_version": "px.health-report/1.0",
        "valid": True,
        "evaluated_at": _format_datetime(evaluation),
        "overall_state": overall,
        "summary": {state: counts[state] for state in STATES},
        "records": records,
    }
    try:
        validate_instance(report, root / REPORT_SCHEMA)
    except ContractValidationError as error:  # pragma: no cover - implementation defect
        raise HealthModelError(
            f"derived health report violates its contract: {error}"
        ) from error
    return report


def validate_health_report(root: Path, report: Mapping[str, object]) -> dict[str, Any]:
    """Re-derive report semantics so a consumer cannot strengthen health claims."""
    root = root.resolve()
    errors: list[str] = []
    try:
        validate_instance(dict(report), root / REPORT_SCHEMA)
        registry = _load_registry(root)
    except (ContractValidationError, HealthModelError, OSError, ValueError) as error:
        return {
            "schema_version": "px.health-report-validation/1.0",
            "valid": False,
            "errors": [str(error)],
        }
    evaluation = _parse_datetime(report["evaluated_at"], "evaluated_at")
    records = report["records"]
    assert isinstance(records, list)
    by_surface = {item["surface_id"]: item for item in registry["surfaces"]}
    identifiers = [record["surface_id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        errors.append("report contains duplicate health surfaces")
    if set(identifiers) != set(by_surface):
        errors.append("report does not cover the canonical health surface set")
    counts: Counter[str] = Counter()
    for record in records:
        surface = by_surface.get(record["surface_id"])
        if surface is None:
            continue
        for field in ("domain", "authority", "remediation"):
            if record[field] != surface[field]:
                errors.append(f"{record['surface_id']}: canonical {field} mismatch")
        freshness = record["freshness"]
        if freshness["ttl_seconds"] != surface["ttl_seconds"]:
            errors.append(f"{record['surface_id']}: canonical TTL mismatch")
        if freshness["evaluated_at"] != _format_datetime(evaluation):
            errors.append(f"{record['surface_id']}: evaluation time mismatch")
        raw_observed = freshness["observed_at"]
        observed = (
            None
            if raw_observed is None
            else _parse_datetime(raw_observed, "freshness.observed_at")
        )
        if observed is not None and observed > evaluation:
            errors.append(f"{record['surface_id']}: observation is in the future")
        try:
            _validate_lifecycle(record["lifecycle"])
            _nullable_event_time(
                record["last_success"], "last_success", evaluation, observed
            )
            _last_failure(record["last_failure"], evaluation, observed)
        except HealthModelError as error:
            errors.append(f"{record['surface_id']}: {error}")
        has_facts = any(record["lifecycle"].values()) or bool(
            record["degradation"]
            or record["blockers"]
            or record["last_success"]
            or record["last_failure"]
        )
        if observed is None and has_facts:
            errors.append(f"{record['surface_id']}: facts require an observation")
        expected_age = (
            None
            if observed is None
            else round(max(0.0, (evaluation - observed).total_seconds()), 6)
        )
        expected_stale = (
            expected_age is not None and expected_age > surface["ttl_seconds"]
        )
        if freshness["age_seconds"] != expected_age:
            errors.append(f"{record['surface_id']}: age does not match timestamps")
        if freshness["stale"] is not expected_stale:
            errors.append(f"{record['surface_id']}: stale flag conflicts with TTL")
        expected_state = _derive_state(
            record["lifecycle"],
            stale=expected_stale,
            last_success=record["last_success"],
            last_failure=record["last_failure"],
            degradation=record["degradation"],
            blockers=record["blockers"],
        )
        if record["state"] != expected_state:
            errors.append(f"{record['surface_id']}: state conflicts with facts")
        counts[record["state"]] += 1
    expected_summary = {state: counts[state] for state in STATES}
    if report["summary"] != expected_summary:
        errors.append("report summary conflicts with records")
    expected_overall = next(
        (state for state in STATE_PRECEDENCE if counts[state]), "unknown"
    )
    if report["overall_state"] != expected_overall:
        errors.append("overall state conflicts with records")
    return {
        "schema_version": "px.health-report-validation/1.0",
        "valid": not errors,
        "errors": errors,
    }


def project_health_for_extension(
    root: Path, report: Mapping[str, object]
) -> dict[str, Any]:
    """Create the read-only extension input; consumers cannot strengthen claims."""
    required = {
        "schema_version",
        "valid",
        "evaluated_at",
        "overall_state",
        "summary",
        "records",
    }
    if (
        set(report) != required
        or report.get("schema_version") != "px.health-report/1.0"
    ):
        raise HealthModelError(
            "extension projection requires a canonical health report"
        )
    validation = validate_health_report(root, report)
    if not validation["valid"]:
        raise HealthModelError(
            f"extension projection rejected health report: {validation['errors']}"
        )
    return {
        "schema_version": "px.extension-health-input/1.0",
        "source_schema_version": report["schema_version"],
        "read_only": True,
        "evaluated_at": report["evaluated_at"],
        "overall_state": report["overall_state"],
        "summary": dict(report["summary"]),
        "records": deepcopy(report["records"]),
    }
