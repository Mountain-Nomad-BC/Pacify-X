"""Fail-closed reconciliation of declared operational visibility coverage.

The route registry is the declaration plane.  Punch-card records provide
acceptance evidence, while a caller-supplied health snapshot provides current
mediator, observer, and sensor state.  Registry declarations alone never count
as live health evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .operational_visibility import TIER_MECHANISMS, validate_route_registry


ROUTE_REGISTRY = Path("registry/operation_route_registry.json")
DEFAULT_EVIDENCE_DIR = Path("evidence/punch-cards")
CARD_ID = re.compile(r"^([A-Z][0-9]{2})(?:\b|[^A-Za-z0-9])")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_FILES = 1_000
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_HEALTH_STATES = 10_000
HEALTH_KINDS = frozenset({"mediator", "observer", "sensor", "attestation"})
HEALTH_VALUES = frozenset({"healthy", "degraded", "unconfigured", "unsupported", "unknown"})


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise ValueError("JSON artifact is missing")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON artifact exceeds the bounded size")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON artifact is unreadable") from error


def _inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_below(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("artifact path is missing")
    relative = Path(raw)
    if relative.is_absolute():
        raise ValueError("artifact path must be project-relative")
    target = (root / relative).resolve()
    if not _inside(target, root) or target == root:
        raise ValueError("artifact path escapes the project root")
    return target


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("observed_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("observed_at requires a timezone")
    return parsed.astimezone(timezone.utc)


def _card_id(requirement: object) -> str | None:
    if not isinstance(requirement, str):
        return None
    match = CARD_ID.match(requirement.strip())
    return match.group(1) if match else None


def _load_acceptance_evidence(root: Path, evidence_dir: Path) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    records: dict[str, dict[str, object]] = {}
    problems: list[dict[str, str]] = []
    directory = evidence_dir if evidence_dir.is_absolute() else root / evidence_dir
    try:
        directory = directory.resolve()
    except OSError:
        problems.append({"code": "evidence_directory_unreadable", "detail": "acceptance evidence directory is unreadable"})
        return records, problems
    if not _inside(directory, root) or not directory.is_dir():
        problems.append({"code": "evidence_directory_unreadable", "detail": "acceptance evidence directory is absent or outside the project"})
        return records, problems
    paths = sorted(directory.glob("*.json"))
    if len(paths) > MAX_EVIDENCE_FILES:
        problems.append({"code": "evidence_limit_exceeded", "detail": "acceptance evidence file count exceeds the bounded limit"})
        paths = paths[:MAX_EVIDENCE_FILES]
    for path in paths:
        try:
            payload = _load_json(path)
        except ValueError:
            problems.append({"code": "evidence_unreadable", "detail": path.name})
            continue
        if not isinstance(payload, dict):
            problems.append({"code": "evidence_invalid", "detail": path.name})
            continue
        card_id = payload.get("card_id")
        if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
            # Non-card JSON may coexist in a caller-selected directory.
            continue
        if card_id in records:
            problems.append({"code": "duplicate_acceptance_evidence", "detail": card_id})
            continue
        records[card_id] = {"path": path, "payload": payload}
    return records, problems


def _validate_acceptance_record(
    root: Path, card_id: str, record: Mapping[str, object]
) -> list[dict[str, str]]:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return [{"code": "acceptance_evidence_invalid", "detail": card_id}]
    problems: list[dict[str, str]] = []
    if payload.get("card_id") != card_id or payload.get("status") != "accepted":
        problems.append({"code": "acceptance_not_accepted", "detail": card_id})
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append({"code": "acceptance_artifacts_missing", "detail": card_id})
        return problems
    seen: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            problems.append({"code": "acceptance_artifact_invalid", "detail": card_id})
            continue
        raw_path = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or not HEX_SHA256.fullmatch(expected):
            problems.append({"code": "acceptance_receipt_invalid", "detail": card_id})
            continue
        try:
            path = _resolve_below(root, raw_path)
        except ValueError:
            problems.append({"code": "acceptance_receipt_invalid", "detail": card_id})
            continue
        key = path.as_posix()
        if key in seen:
            problems.append({"code": "acceptance_artifact_duplicate", "detail": card_id})
            continue
        seen.add(key)
        try:
            actual = _file_sha256(path)
        except OSError:
            problems.append({"code": "acceptance_artifact_missing", "detail": f"{card_id}:{raw_path}"})
            continue
        if actual != expected:
            problems.append({"code": "acceptance_receipt_mismatch", "detail": f"{card_id}:{raw_path}"})
    return problems


def _external_owner_receipt(
    root: Path,
    owner: object,
    required_cards: list[str],
    evidence: Mapping[str, Mapping[str, object]],
    validated_cards: Mapping[str, list[dict[str, str]]],
) -> dict[str, str] | None:
    """Resolve an external owner only through accepted, hash-bound local proof.

    External extension sources are intentionally not treated as project files.
    Their accepted punch-card record must hash-bind a local verification receipt,
    and that receipt must name the exact owner path and its SHA-256.  This keeps
    reconciliation portable without silently accepting an absent owner.
    """
    if not isinstance(owner, str) or not owner.strip():
        return None
    raw_owner = owner.strip().replace("\\", "/")
    owner_path = Path(raw_owner)
    if owner_path.is_absolute() or any(part in {"", ".", ".."} for part in owner_path.parts):
        return None
    for card_id in required_cards:
        if validated_cards.get(card_id):
            continue
        record = evidence.get(card_id)
        payload = record.get("payload") if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                continue
            try:
                receipt_path = _resolve_below(root, artifact.get("path"))
                receipt = _load_json(receipt_path)
            except ValueError:
                continue
            if not isinstance(receipt, Mapping):
                continue
            if receipt.get("schema_version") != "px.external-extension-verification/1.0":
                continue
            external_root = receipt.get("extension_root")
            owner_artifacts = receipt.get("artifacts")
            if not isinstance(external_root, str) or not external_root.strip():
                continue
            if not isinstance(owner_artifacts, Mapping):
                continue
            owner_sha256 = owner_artifacts.get(raw_owner)
            if not isinstance(owner_sha256, str) or not HEX_SHA256.fullmatch(owner_sha256):
                continue
            return {
                "mode": "external_hash_bound_receipt",
                "card_id": card_id,
                "receipt_path": receipt_path.relative_to(root).as_posix(),
                "owner": raw_owner,
                "owner_sha256": owner_sha256,
            }
    return None


def _load_health_snapshot(snapshot: Mapping[str, object] | Path | None) -> tuple[list[Mapping[str, object]], list[dict[str, str]], str | None]:
    if snapshot is None:
        return [], [], None
    source_sha256: str | None = None
    if isinstance(snapshot, Path):
        try:
            source_sha256 = _file_sha256(snapshot)
            loaded = _load_json(snapshot)
        except (OSError, ValueError):
            return [], [{"code": "health_snapshot_unreadable", "detail": "health snapshot is unreadable"}], None
    else:
        loaded = dict(snapshot)
        source_sha256 = _canonical_sha256(loaded)
    if not isinstance(loaded, Mapping) or loaded.get("schema_version") != "px.operation-coverage-health/1.0":
        return [], [{"code": "health_snapshot_invalid", "detail": "health snapshot schema_version is invalid"}], source_sha256
    states = loaded.get("route_states")
    if not isinstance(states, list):
        return [], [{"code": "health_snapshot_invalid", "detail": "route_states must be an array"}], source_sha256
    if len(states) > MAX_HEALTH_STATES:
        return [], [{"code": "health_snapshot_invalid", "detail": "route_states exceeds the bounded limit"}], source_sha256
    valid_states: list[Mapping[str, object]] = []
    problems: list[dict[str, str]] = []
    for index, state in enumerate(states):
        if not isinstance(state, Mapping):
            problems.append({"code": "health_state_invalid", "detail": str(index)})
            continue
        valid_states.append(state)
    return valid_states, problems, source_sha256


def reconcile_operation_coverage(
    root: Path,
    *,
    health_snapshot: Mapping[str, object] | Path | None = None,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    now: datetime | None = None,
    max_age_seconds: int = 300,
) -> dict[str, Any]:
    """Reconcile static claims, current health, and hash-bound acceptance proof."""
    root = root.resolve()
    if not 1 <= max_age_seconds <= 86_400:
        raise ValueError("max_age_seconds must be between 1 and 86400")
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    registry_report = validate_route_registry(root)
    blockers: list[dict[str, str]] = []
    errors: list[str] = list(registry_report.get("errors", ()))
    if not registry_report.get("valid"):
        blockers.append({"code": "registry_invalid", "detail": "route registry failed structural or tier honesty validation"})
    try:
        loaded_registry = _load_json(root / ROUTE_REGISTRY)
    except ValueError as error:
        loaded_registry = {"routes": []}
        errors.append(str(error))
    routes = loaded_registry.get("routes", []) if isinstance(loaded_registry, Mapping) else []
    route_by_id = {
        str(route.get("route_id")): route
        for route in routes
        if isinstance(route, Mapping) and isinstance(route.get("route_id"), str)
    }

    evidence, evidence_problems = _load_acceptance_evidence(root, evidence_dir)
    blockers.extend(evidence_problems)
    states, health_problems, health_sha256 = _load_health_snapshot(health_snapshot)
    blockers.extend(health_problems)
    state_by_route: dict[str, Mapping[str, object]] = {}
    for state in states:
        route_id = state.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            blockers.append({"code": "health_state_invalid", "detail": "route_id is missing"})
            continue
        if route_id not in route_by_id:
            blockers.append({"code": "unknown_route_state", "detail": route_id})
            continue
        if route_id in state_by_route:
            blockers.append({"code": "duplicate_route_state", "detail": route_id})
            continue
        state_by_route[route_id] = state

    validated_cards: dict[str, list[dict[str, str]]] = {}
    route_reports: list[dict[str, object]] = []
    blind_spots: list[dict[str, str]] = []
    cutoff = clock - timedelta(seconds=max_age_seconds)
    future_limit = clock + timedelta(seconds=60)
    for route_id, route in route_by_id.items():
        route_blockers: list[dict[str, str]] = []
        tier = str(route.get("coverage_tier"))
        instrumentation = route.get("instrumentation")
        instrumentation = instrumentation if isinstance(instrumentation, Mapping) else {}
        mechanism = str(instrumentation.get("kind", ""))
        active = route.get("advertised") is True
        planned_inactive = not active and route.get("status") == "planned"
        expected_mechanism = TIER_MECHANISMS.get(tier)
        if expected_mechanism and mechanism != expected_mechanism:
            route_blockers.append({"code": "dishonest_tier", "detail": f"Tier {tier} requires {expected_mechanism}"})
        required_cards: list[str] = []
        for requirement in route.get("acceptance_evidence", []):
            card = _card_id(requirement)
            if card is None:
                route_blockers.append({"code": "acceptance_reference_invalid", "detail": route_id})
                continue
            if card not in required_cards:
                required_cards.append(card)
        for card in required_cards:
            if planned_inactive:
                continue
            record = evidence.get(card)
            if record is None:
                route_blockers.append({"code": "acceptance_evidence_missing", "detail": card})
                continue
            if card not in validated_cards:
                validated_cards[card] = _validate_acceptance_record(root, card, record)
            route_blockers.extend(validated_cards[card])

        owner = route.get("owner")
        owner_evidence: dict[str, str] | None = None
        try:
            owner_path = _resolve_below(root, owner)
            if not owner_path.is_file():
                raise ValueError("owner missing")
            owner_evidence = {
                "mode": "local_file",
                "owner": owner_path.relative_to(root).as_posix(),
                "owner_sha256": _file_sha256(owner_path),
            }
        except (OSError, ValueError):
            if route.get("surface") in {"extension", "mcp"}:
                owner_evidence = _external_owner_receipt(
                    root, owner, required_cards, evidence, validated_cards
                )
            if owner_evidence is None:
                route_blockers.append({"code": "route_owner_missing", "detail": route_id})

        if tier == "D":
            blind = str(route.get("blind_spot_state", "unobserved"))
            blind_spots.append({"route_id": route_id, "state": blind})
            if route.get("advertised") is True:
                route_blockers.append({"code": "declared_blind_spot", "detail": blind})
            if mechanism != "none":
                route_blockers.append({"code": "dishonest_tier", "detail": "Tier D requires no instrumentation claim"})
        else:
            if active and instrumentation.get("health") != "healthy":
                route_blockers.append({"code": "declared_instrumentation_unhealthy", "detail": str(instrumentation.get("health"))})
            state = state_by_route.get(route_id)
            if tier in {"A", "B"} and active:
                if state is None:
                    route_blockers.append({"code": "required_health_state_missing", "detail": route_id})
                else:
                    kind = state.get("kind")
                    allowed_kinds = {"mediator"} if tier == "A" else {"observer", "sensor"}
                    if kind not in allowed_kinds or kind not in HEALTH_KINDS:
                        route_blockers.append({"code": "health_kind_mismatch", "detail": str(kind)})
                    health = state.get("health")
                    if health not in HEALTH_VALUES or health != "healthy":
                        route_blockers.append({"code": "route_health_unhealthy", "detail": str(health)})
                    try:
                        observed_at = _parse_time(state.get("observed_at"))
                        if observed_at < cutoff or observed_at > future_limit:
                            route_blockers.append({"code": "route_health_stale", "detail": route_id})
                    except ValueError:
                        route_blockers.append({"code": "route_health_time_invalid", "detail": route_id})
                    expected_sha = state.get("receipt_sha256")
                    if not isinstance(expected_sha, str) or not HEX_SHA256.fullmatch(expected_sha):
                        route_blockers.append({"code": "health_receipt_invalid", "detail": route_id})
                    else:
                        try:
                            receipt = _resolve_below(root, state.get("receipt_path"))
                            actual_sha = _file_sha256(receipt)
                        except (OSError, ValueError):
                            route_blockers.append({"code": "health_receipt_missing", "detail": route_id})
                        else:
                            if actual_sha != expected_sha:
                                route_blockers.append({"code": "health_receipt_mismatch", "detail": route_id})
        for blocker in route_blockers:
            blockers.append({**blocker, "route_id": route_id})
        route_reports.append(
            {
                "route_id": route_id,
                "tier": tier,
                "declared": True,
                "advertised": route.get("advertised") is True,
                "certifiable": not route_blockers,
                "required_acceptance_cards": required_cards,
                "owner_evidence": owner_evidence,
                "health_state_present": route_id in state_by_route,
                "blockers": route_blockers,
            }
        )

    input_invalid_codes = {
        "registry_invalid",
        "evidence_directory_unreadable",
        "evidence_limit_exceeded",
        "evidence_unreadable",
        "evidence_invalid",
        "duplicate_acceptance_evidence",
        "health_snapshot_unreadable",
        "health_snapshot_invalid",
        "health_state_invalid",
        "unknown_route_state",
        "duplicate_route_state",
    }
    input_valid = not errors and not any(item["code"] in input_invalid_codes for item in blockers)
    return {
        "schema_version": "px.operation-coverage-report/1.0",
        "valid": input_valid,
        "certifiable": input_valid and not blockers,
        "route_registry_sha256": _file_sha256(root / ROUTE_REGISTRY) if (root / ROUTE_REGISTRY).is_file() else None,
        "health_snapshot_sha256": health_sha256,
        "route_count": len(route_by_id),
        "classified_route_count": sum(1 for route in routes if isinstance(route, Mapping) and route.get("coverage_tier") in {"A", "B", "C", "D"}),
        "tiers": registry_report.get("tiers", {tier: 0 for tier in "ABCD"}),
        "acceptance_cards_loaded": sorted(evidence),
        "blind_spots": blind_spots,
        "routes": route_reports,
        "blockers": blockers,
        "errors": errors,
    }
