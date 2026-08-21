"""Append-only operational gap ledger with an evidence-bound state machine.

The JSONL event stream is authoritative.  The JSON snapshot is a deterministic
projection and may always be rebuilt from the stream.
"""

from __future__ import annotations

from collections import Counter
import base64
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .file_lock import FileLock


SCHEMA = "px.operational-gap-ledger-event/1.0"
SNAPSHOT_SCHEMA = "px.operational-gap-ledger-snapshot/1.0"
HEAD_SCHEMA = "px.operational-gap-ledger-head/1.0"
LEDGER_RELATIVE = Path("registry/operational_gap_ledger.jsonl")
SNAPSHOT_RELATIVE = Path("registry/operational_gap_ledger.snapshot.json")
HEAD_RELATIVE = Path("registry/operational_gap_ledger.head.json")
LOCK_RELATIVE = Path("registry/.operational-gap-ledger.lock")
MAX_LEDGER_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_HEAD_BYTES = 512 * 1024
MAX_EVENT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_BATCH_EVENTS = 1_000
MAX_EVENTS = 100_000
GAP_ID_PATTERN = re.compile(r"^PX-(?:OS|GAP)-[0-9]{3,}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
NON_VISIBLE_PATH_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{2,200}$")

PRIMARY_STATES = (
    "discovered", "reproduced", "scoped", "approved", "implementing",
    "implemented", "narrowly_verified", "integrated",
    "operationally_verified", "closed",
)
NON_TERMINAL_STATES = ("blocked", "deferred", "superseded", "reopened")
STATES = frozenset(PRIMARY_STATES + NON_TERMINAL_STATES)
CLASSIFICATIONS = frozenset(
    {
        "UI", "editor", "backend", "runtime", "persistence", "revisioning",
        "recovery", "integration", "host-owned", "intentionally-unsupported",
        "out-of-scope", "documentation",
    }
)
SEVERITIES = frozenset({"blocker", "critical", "high", "medium", "low"})
CHAIN_STAGES = (
    "open_load", "display", "user_edit_action", "input_validation",
    "authorization", "backend_dispatch", "runtime_effect",
    "progress_reporting", "result_acknowledgement", "persistence",
    "reload_reopen", "failure_handling", "recovery_rollback",
)
CHAIN_STATES = frozenset({"present", "partial", "missing", "not_applicable", "unknown"})
CONTROL_OBSERVATION_SCHEMA = "px.control-observation/1.0"
CONTROL_OBSERVATION_SCHEMA_V2 = "px.control-observation/2.0"
CONTROL_EVIDENCE_MODES = frozenset(
    {
        "live_ui", "contained_ui_interaction", "contained_host_interaction",
        "contained_sidebar_interaction", "contained_ui_input",
        "contained_ui_form", "contained_ui_navigation", "contained_ui_editor",
        "contained_ui_gesture", "live_state_observation",
        "isolated_host_command", "contained_runtime_lifecycle",
        "contained_durability", "contained_restart",
        "contained_fault_injection", "live_acknowledgement",
    }
)
NON_RENDERED_CONTROL_KINDS = frozenset(
    {"lifecycle", "persistence", "reload_reopen", "failure_recovery", "acknowledgement"}
)
CONTROL_OBSERVATION_OUTCOMES = frozenset(
    {
        "operational", "observed_gap", "observed_only",
        "skipped_requires_authority", "not_rendered", "ambiguous",
    }
)
CONTROL_KINDS = frozenset(
    {
        "action", "menu", "field", "form", "editor", "gesture", "indicator",
        "command", "lifecycle", "agent_operation", "workflow_operation",
        "skill_plugin_binding", "persistence", "reload_reopen",
        "failure_recovery", "progress_indicator", "acknowledgement",
    }
)
EVENT_TYPES = frozenset(
    {
        "ledger_initialized", "surface_registered", "surface_examined",
        "expected_inventory_registered", "expected_inventory_revised",
        "surface_alias_registered", "surface_controls_added", "surface_inventory_revised", "control_disposition",
        "control_disposition_revised",
        "card_discovered", "card_annotated", "card_transition",
        "card_control_scope_set", "card_control_scope_revised",
        "card_evidence_attested",
        "transition_admission_backfilled",
        "report_registered", "report_finding_reconciled",
        "card_relationship", "work_checkpoint", "work_admitted",
    }
)
CARD_REQUIRED = (
    "gap_id", "parent_surface", "feature", "control_action", "discovery_source",
    "discovered_at", "discovered_by", "source_refs", "expected_behavior",
    "observed_behavior", "interaction_chain", "classification", "severity",
    "operational_impact", "dependencies", "blockers", "assigned_owner",
    "tests_required", "completion_evidence", "next_action",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _inside(root: Path, target: Path) -> Path:
    root = root.resolve(strict=True)
    candidate = target.resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError("operational ledger path escapes project root")
    return candidate


def _read_bounded_regular(path: Path, maximum: int, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing or not a physical file")
    with path.open("rb") as handle:
        value = os.fstat(handle.fileno())
        if not stat.S_ISREG(value.st_mode) or value.st_size > maximum:
            raise ValueError(f"{label} exceeds its physical-file bound")
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"{label} exceeds its byte bound")
    return data


def _nonempty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _iso_utc(value: object, field: str) -> datetime:
    _nonempty(value, field)
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _evidence(value: object, field: str = "evidence") -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must contain at least one evidence reference")
    rows: list[dict[str, object]] = []
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
            if not SHA256_PATTERN.fullmatch(artifact_sha256):
                raise ValueError(f"{field} artifact_sha256 is invalid")
            row["artifact_sha256"] = artifact_sha256
            if "artifact_size" in item:
                size = item["artifact_size"]
                if not isinstance(size, int) or size < 0:
                    raise ValueError(f"{field} artifact_size is invalid")
                row["artifact_size"] = size
        rows.append(row)
    return rows


def _validate_chain(value: object, *, require_evidence: bool = False) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping) or set(value) != set(CHAIN_STAGES):
        raise ValueError("interaction_chain must contain every required stage exactly once")
    result: dict[str, dict[str, object]] = {}
    for stage in CHAIN_STAGES:
        item = value[stage]
        if not isinstance(item, Mapping) or item.get("state") not in CHAIN_STATES:
            raise ValueError(f"interaction_chain.{stage} has an invalid state")
        detail = str(item.get("detail") or "").strip()
        if not detail:
            raise ValueError(f"interaction_chain.{stage} requires detail")
        refs = item.get("evidence", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
            raise ValueError(f"interaction_chain.{stage}.evidence must be string references")
        if require_evidence and item["state"] in {"present", "partial"} and not refs:
            raise ValueError(f"interaction_chain.{stage} requires evidence for {item['state']}")
        result[stage] = {"state": item["state"], "detail": detail, "evidence": list(refs)}
    return result


def _validate_control_observation(
    value: object, *, disposition: str, expected_kind: str | None = None
) -> dict[str, object]:
    """Validate exact current-host evidence without rewriting legacy events.

    Historical dispositions predate this contract and remain replayable, but
    only a disposition carrying this object contributes to current examination
    or operational-proof progress.
    """

    if not isinstance(value, Mapping):
        raise ValueError("control disposition observation must be an object")
    schema_version = str(value.get("schema_version") or "") if isinstance(value, Mapping) else ""
    if schema_version not in {CONTROL_OBSERVATION_SCHEMA, CONTROL_OBSERVATION_SCHEMA_V2}:
        raise ValueError("control disposition observation schema is invalid")
    outcome = str(value.get("outcome") or "")
    if outcome not in CONTROL_OBSERVATION_OUTCOMES:
        raise ValueError("control disposition observation outcome is invalid")
    for field in ("authority", "observed_at"):
        _nonempty(value.get(field), f"control disposition observation {field}")
    source = value.get("source_identity")
    if not isinstance(source, Mapping):
        raise ValueError("control disposition observation source_identity is invalid")
    for field in ("kind", "source_sha256"):
        _nonempty(source.get(field), f"control disposition source_identity {field}")
    if not SHA256_PATTERN.fullmatch(str(source["source_sha256"]).lower()):
        raise ValueError("control disposition source identity hash is invalid")
    if not isinstance(source.get("current_source"), bool) or not isinstance(
        source.get("host_source_mismatch"), bool
    ):
        raise ValueError("control disposition source identity flags are invalid")
    rendered = value.get("rendered")
    attempted = value.get("attempted")
    if not isinstance(rendered, bool) or not isinstance(attempted, bool):
        raise ValueError("control disposition observation flags are invalid")
    chain = _validate_chain(value.get("interaction_chain"), require_evidence=True)
    if any(not item["evidence"] for item in chain.values()):
        raise ValueError("control disposition observation requires evidence for every interaction stage")
    control_kind = str(value.get("control_kind") or "")
    evidence_mode = str(value.get("evidence_mode") or "")
    observed = value.get("observed")
    if schema_version == CONTROL_OBSERVATION_SCHEMA_V2:
        if control_kind not in CONTROL_KINDS:
            raise ValueError("control disposition observation control_kind is invalid")
        if expected_kind is not None and control_kind != expected_kind:
            raise ValueError("control disposition observation kind differs from the registered control")
        if evidence_mode not in CONTROL_EVIDENCE_MODES:
            raise ValueError("control disposition observation evidence_mode is invalid")
        if not isinstance(observed, bool):
            raise ValueError("control disposition observation observed flag is invalid")
    else:
        observed = rendered
    if disposition == "operational":
        if outcome != "operational":
            raise ValueError("operational disposition requires an operational observation outcome")
        if not source["current_source"] or source["host_source_mismatch"]:
            raise ValueError("operational disposition requires exact current-source host identity")
        if not observed or not attempted:
            raise ValueError("operational disposition requires an observed and attempted control")
        if schema_version == CONTROL_OBSERVATION_SCHEMA and not rendered:
            raise ValueError("operational disposition requires a rendered and attempted control")
        if (
            schema_version == CONTROL_OBSERVATION_SCHEMA_V2
            and control_kind not in NON_RENDERED_CONTROL_KINDS
            and not rendered
        ):
            raise ValueError("operational visible control disposition requires rendered evidence")
        unresolved = [
            stage for stage, item in chain.items()
            if item["state"] not in {"present", "not_applicable"}
        ]
        if unresolved:
            raise ValueError(
                f"operational disposition requires a complete interaction chain: {unresolved}"
            )
    elif outcome == "operational":
        raise ValueError("gap disposition cannot carry an operational observation outcome")
    if outcome in {"not_rendered", "ambiguous"} and (rendered or attempted):
        raise ValueError(f"{outcome} observation cannot be rendered or attempted")
    if outcome == "skipped_requires_authority" and (not rendered or attempted):
        raise ValueError("skipped control must be rendered and not attempted")
    result = {
        "schema_version": schema_version,
        "outcome": outcome,
        "authority": str(value["authority"]),
        "observed_at": str(value["observed_at"]),
        "source_identity": {
            "kind": str(source["kind"]),
            "source_sha256": str(source["source_sha256"]).lower(),
            "current_source": bool(source["current_source"]),
            "host_source_mismatch": bool(source["host_source_mismatch"]),
        },
        "rendered": rendered,
        "attempted": attempted,
        "interaction_chain": chain,
    }
    if schema_version == CONTROL_OBSERVATION_SCHEMA_V2:
        result.update({
            "control_kind": control_kind,
            "evidence_mode": evidence_mode,
            "observed": bool(observed),
        })
    return result


def blank_interaction_chain(detail: str = "Not yet exercised in the installed host.") -> dict[str, dict[str, object]]:
    return {stage: {"state": "unknown", "detail": detail, "evidence": []} for stage in CHAIN_STAGES}


def _controls_sha256(controls: Iterable[str]) -> str:
    encoded = json.dumps(sorted(map(str, controls)), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def control_disposition_sha256(disposition: Mapping[str, Any]) -> str:
    """Return the canonical predecessor identity for a control disposition."""

    value = dict(disposition)
    if value.get("proof_status") == "legacy_unbound" and value.get("observation") is None:
        # These derived fields did not exist when historical predecessor hashes
        # were committed.  Omitting only the absent legacy projection preserves
        # that identity; current typed observations remain hash-bound.
        value.pop("proof_status", None)
        value.pop("observation", None)
    return _digest(value)


def card_control_scope_sha256(disposition: Mapping[str, Any]) -> str:
    """Return the predecessor identity for an explicit card control scope."""

    return _digest(dict(disposition))


def evidence_reference_sha256(evidence: Mapping[str, Any]) -> str:
    """Identify a historical evidence claim independent of later attestations."""

    return _digest(
        {
            "reference": str(evidence.get("reference") or ""),
            "claim": str(evidence.get("claim") or ""),
        }
    )


def _validate_card_control_scope(
    cards: Mapping[str, Mapping[str, Any]],
    relationships: list[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    gap_id = str(payload.get("gap_id") or "")
    if gap_id not in cards:
        raise ValueError("card control scope references an unknown card")
    kind = str(payload.get("kind") or "")
    if kind not in {"aggregate_parent", "non_visible_path", "typed_controls"}:
        raise ValueError("card control scope kind is invalid")
    for field in ("reason", "authority", "return_condition"):
        _nonempty(payload.get(field), f"card control scope {field}")
    result: dict[str, Any] = {
        "kind": kind,
        "reason": str(payload["reason"]),
        "authority": str(payload["authority"]),
        "return_condition": str(payload["return_condition"]),
    }
    if kind == "aggregate_parent":
        children = payload.get("child_gap_ids")
        if (
            not isinstance(children, list)
            or not children
            or len(children) != len(set(map(str, children)))
            or gap_id in set(map(str, children))
            or any(str(child) not in cards for child in children)
        ):
            raise ValueError("aggregate card control scope requires distinct known child cards")
        declared = {
            (str(item.get("parent_gap_id") or ""), str(item.get("child_gap_id") or ""))
            for item in relationships
            if item.get("relationship") == "child"
        }
        if any((gap_id, str(child)) not in declared for child in children):
            raise ValueError("aggregate card control scope requires explicit child relationships")
        result["child_gap_ids"] = list(map(str, children))
    elif kind == "non_visible_path":
        path_id = str(payload.get("path_id") or "")
        if not NON_VISIBLE_PATH_ID_PATTERN.fullmatch(path_id):
            raise ValueError("non-visible card control scope path_id is invalid")
        source_refs = payload.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise ValueError("non-visible card control scope requires source_refs")
        for ref in source_refs:
            if (
                not isinstance(ref, Mapping)
                or not str(ref.get("path") or "").strip()
                or not isinstance(ref.get("symbols"), list)
                or not ref.get("symbols")
                or any(not isinstance(symbol, str) or not symbol.strip() for symbol in ref["symbols"])
            ):
                raise ValueError("non-visible card control scope source_refs are invalid")
        result["path_id"] = path_id
        result["source_refs"] = json.loads(_canonical(source_refs))
    return result


def _validate_control_records(value: object) -> tuple[list[str], dict[str, dict[str, object]]]:
    if not isinstance(value, list) or not value:
        raise ValueError("surface inventory controls must be a non-empty array")
    records: dict[str, dict[str, object]] = {}
    for original in value:
        if not isinstance(original, Mapping):
            raise ValueError("surface inventory control entries must be objects")
        control_id = str(original.get("control_id") or "").strip()
        kind = str(original.get("kind") or "").strip()
        label = str(original.get("label") or "").strip()
        source_refs = original.get("source_refs")
        if not control_id or control_id in records:
            raise ValueError("surface inventory control IDs must be non-empty and unique")
        if kind not in CONTROL_KINDS:
            raise ValueError(f"surface inventory control kind is invalid: {kind}")
        if not label or not isinstance(source_refs, list) or not source_refs or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs):
            raise ValueError("surface inventory controls require label and source_refs")
        records[control_id] = {
            "control_id": control_id,
            "kind": kind,
            "label": label,
            "source_refs": list(source_refs),
        }
    return sorted(records), {key: records[key] for key in sorted(records)}


def _transition_allowed(before: str, after: str) -> bool:
    if before not in STATES or after not in STATES or before == after:
        return False
    if after == "reopened":
        return before not in {"discovered", "reproduced"}
    if before == "reopened":
        return after == "reproduced"
    if after in {"blocked", "deferred", "superseded"}:
        return True
    try:
        return PRIMARY_STATES.index(after) == PRIMARY_STATES.index(before) + 1
    except ValueError:
        return False


def _validate_card(
    card: Mapping[str, Any], allow_local_discovery_empty_symbols: bool = False
) -> dict[str, Any]:
    missing = [field for field in CARD_REQUIRED if field not in card]
    if missing:
        raise ValueError(f"card is missing required fields: {missing}")
    for field in (
        "gap_id", "parent_surface", "feature", "control_action", "discovery_source",
        "discovered_at", "discovered_by", "expected_behavior", "observed_behavior",
        "operational_impact", "assigned_owner", "next_action",
    ):
        _nonempty(card[field], field)
    if not GAP_ID_PATTERN.fullmatch(str(card["gap_id"])):
        raise ValueError("gap_id must use the canonical PX-OS-NNN or PX-GAP-NNN format")
    if card["classification"] not in CLASSIFICATIONS:
        raise ValueError("card classification is invalid")
    if str(card["severity"]).lower() not in SEVERITIES:
        raise ValueError("card severity is invalid")
    if not isinstance(card["source_refs"], list) or not card["source_refs"]:
        raise ValueError("source_refs must contain at least one source reference")
    discovery_source = str(card.get("discovery_source") or "").strip()
    for ref in card["source_refs"]:
        # Historical discovery events predate symbol-bound source references.
        # Replay must preserve those events long enough for a later annotation
        # to repair them.  New appends remain fail-closed in
        # ``_prepare_event`` below, which permits an empty symbol list only for
        # the exact hash-bound local discovery source.
        allow_empty_symbols = allow_local_discovery_empty_symbols
        if (
            not isinstance(ref, Mapping)
            or not str(ref.get("path") or "").strip()
            or not isinstance(ref.get("symbols"), list)
            or (not ref["symbols"] and not allow_empty_symbols)
            or any(not isinstance(symbol, str) or not symbol.strip() for symbol in ref["symbols"])
        ):
            raise ValueError("source_refs require a path and a non-empty symbols array")
    _iso_utc(card["discovered_at"], "discovered_at")
    for field in ("dependencies", "blockers", "tests_required", "completion_evidence"):
        if not isinstance(card[field], list):
            raise ValueError(f"{field} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in card["completion_evidence"]):
        raise ValueError("completion_evidence entries must be non-empty strings")
    chain = _validate_chain(card["interaction_chain"])
    result = json.loads(_canonical(dict(card)))
    result["severity"] = str(card["severity"]).lower()
    result["interaction_chain"] = chain
    result["current_state"] = "discovered"
    return result


def _validate_current_card(card: Mapping[str, Any]) -> None:
    """Revalidate every mutable card field after an annotation patch."""

    # A non-source annotation on a legacy card must not make the entire ledger
    # unreplayable before a later source-reference correction can be applied.
    # Append-time validation still rejects newly introduced empty symbols, and
    # the progress projection keeps every remaining legacy omission visible.
    _validate_card(
        {field: card[field] for field in CARD_REQUIRED},
        allow_local_discovery_empty_symbols=True,
    )


def _resolved_evidence_path(root: Path, reference: str) -> Path | None:
    value = reference.split("#", 1)[0].strip()
    value = re.sub(r":\d+(?::\d+)?$", "", value)
    if value.startswith("sha256:"):
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve(strict=True)
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if candidate != root and root not in candidate.parents:
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return candidate


def _validate_report_manifest(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bind report registration to its physical machine-readable denominator."""

    source = str(payload.get("source") or "").strip()
    if not source:
        raise ValueError("report source must be a non-empty local path")
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = _inside(root, candidate)
    data = _read_bounded_regular(candidate, MAX_REPORT_BYTES, "operational audit report")
    actual_sha256 = hashlib.sha256(data).hexdigest()
    claimed_sha256 = str(payload.get("source_sha256") or "").lower()
    if claimed_sha256 != actual_sha256:
        raise ValueError("report source_sha256 does not match physical report bytes")
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("report must be a UTF-8 machine-readable JSON manifest") from error
    if not isinstance(manifest, Mapping):
        raise ValueError("report manifest must be an object")
    embedded = manifest.get("finding_ids")
    if (
        not isinstance(embedded, list)
        or not embedded
        or any(not isinstance(item, str) or not item.strip() for item in embedded)
        or len(embedded) != len(set(embedded))
    ):
        raise ValueError("report manifest finding_ids must be a non-empty unique array")
    declared = payload.get("finding_ids")
    if not isinstance(declared, list) or list(map(str, declared)) != embedded:
        raise ValueError("registered finding_ids do not exactly match the report manifest")
    findings = manifest.get("findings")
    if findings is not None:
        if not isinstance(findings, list) or any(not isinstance(item, Mapping) for item in findings):
            raise ValueError("report manifest findings must be an array of objects")
        detailed = [str(item.get("finding_id") or "") for item in findings]
        if detailed != embedded:
            raise ValueError("report findings do not exactly match the embedded finding_ids denominator")
    return {
        "source": candidate.relative_to(root.resolve(strict=True)).as_posix(),
        "source_sha256": actual_sha256,
        "source_size_bytes": len(data),
        "finding_ids": list(embedded),
    }


def _bind_evidence(root: Path, value: object) -> object:
    """Copy a payload while binding resolvable local evidence to immutable bytes."""

    if isinstance(value, list):
        return [_bind_evidence(root, item) for item in value]
    if not isinstance(value, Mapping):
        return value
    result = {str(key): _bind_evidence(root, item) for key, item in value.items()}
    reference = result.get("reference")
    claim = result.get("claim")
    if isinstance(reference, str) and isinstance(claim, str) and "artifact_sha256" not in result:
        path = _resolved_evidence_path(root, reference)
        if path is not None:
            data = path.read_bytes()
            result["artifact_sha256"] = hashlib.sha256(data).hexdigest()
            result["artifact_size"] = len(data)
    return result


def _event_body(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_sha256"}


def _read_events_unlocked(root: Path) -> list[dict[str, Any]]:
    root = root.resolve(strict=True)
    path = _inside(root, root / LEDGER_RELATIVE)
    if not path.exists():
        return []
    return _parse_jsonl_bytes(
        _read_bounded_regular(path, MAX_LEDGER_BYTES, "operational gap ledger")
    )


def read_events(root: Path) -> list[dict[str, Any]]:
    root = root.resolve(strict=True)
    lock = _inside(root, root / LOCK_RELATIVE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock, timeout_seconds=30.0):
        return _read_events_unlocked(root)


def _admission_field_for_state(state: str) -> str | None:
    return {
        "implemented": "implementation_evidence",
        "narrowly_verified": "verification",
        "integrated": "integration_evidence",
        "operationally_verified": "operational_evidence",
    }.get(state)


def _validate_admission_fragment(state: str, admission: object) -> dict[str, Any]:
    field = _admission_field_for_state(state)
    if field is None or not isinstance(admission, Mapping) or set(admission) != {field}:
        raise ValueError("transition admission backfill has an invalid admission field")
    value = json.loads(_canonical(dict(admission)))
    if field == "verification":
        verification = value[field]
        if not isinstance(verification, Mapping):
            raise ValueError("transition admission backfill verification is invalid")
        tests_run = verification.get("tests_run")
        if not isinstance(tests_run, list) or not tests_run or any(
            not isinstance(item, str) or not item.strip() for item in tests_run
        ):
            raise ValueError("transition admission backfill verification tests are invalid")
        _evidence(verification.get("results"), "verification.results")
    else:
        _evidence(value[field], field)
    return value


def _validated_transition_admission_backfills(
    events: list[Mapping[str, Any]],
    *,
    start_sequence: int,
    previous_hash: str | None,
    allow_historical_targets: bool,
) -> dict[str, dict[str, Any]]:
    """Authenticate envelopes before later backfills may affect replay semantics."""

    event_ids: set[str] = set()
    transitions: dict[str, dict[str, Any]] = {}
    cursor = previous_hash
    for sequence, original in enumerate(events, start_sequence):
        event = dict(original)
        if event.get("schema_version") != SCHEMA or event.get("event_type") not in EVENT_TYPES:
            raise ValueError(f"event {sequence} has an unsupported schema or type")
        if event.get("sequence") != sequence or event.get("previous_event_sha256") != cursor:
            raise ValueError(f"event {sequence} breaks sequence or hash-chain continuity")
        if event.get("event_sha256") != _digest(_event_body(event)):
            raise ValueError(f"event {sequence} has an invalid content hash")
        _nonempty(event.get("event_id"), "event_id")
        event_id = str(event["event_id"])
        if event_id in event_ids:
            raise ValueError(f"event {sequence} reuses event_id {event_id}")
        event_ids.add(event_id)
        _nonempty(event.get("timestamp"), "timestamp")
        _nonempty(event.get("actor"), "actor")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError(f"event {sequence} payload must be an object")
        if event["event_type"] == "card_transition":
            transitions[str(event["event_sha256"])] = event
        cursor = str(event["event_sha256"])

    validated: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "transition_admission_backfilled":
            continue
        if not allow_historical_targets:
            raise ValueError(
                "transition admission backfills require an authoritative full replay append"
            )
        payload = event["payload"]
        finding_id = str(payload.get("finding_id") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        _nonempty(finding_id, "finding_id")
        _nonempty(reason, "reason")
        _evidence(payload.get("evidence"))
        attestations = payload.get("attestations")
        if not isinstance(attestations, list) or not attestations or len(attestations) > 100:
            raise ValueError("transition admission backfill attestations are invalid")
        for original in attestations:
            if not isinstance(original, Mapping):
                raise ValueError("transition admission backfill attestation must be an object")
            target_sha = str(original.get("target_event_sha256") or "").lower()
            target = transitions.get(target_sha)
            if target is None or int(target["sequence"]) >= int(event["sequence"]):
                raise ValueError("transition admission backfill target is unknown or not prior")
            target_payload = target["payload"]
            if (
                original.get("target_sequence") != target["sequence"]
                or original.get("target_event_id") != target["event_id"]
                or original.get("gap_id") != target_payload.get("gap_id")
                or original.get("to_state") != target_payload.get("to_state")
            ):
                raise ValueError("transition admission backfill does not bind its exact target")
            if target_sha in validated:
                raise ValueError("transition admission was backfilled more than once")
            validated[target_sha] = {
                "finding_id": finding_id,
                "backfill_event_id": event["event_id"],
                "target_sequence": target["sequence"],
                "target_event_id": target["event_id"],
                "target_event_sha256": target_sha,
                "gap_id": target_payload["gap_id"],
                "to_state": target_payload["to_state"],
                "admission": _validate_admission_fragment(
                    str(target_payload.get("to_state") or ""),
                    original.get("admission"),
                ),
            }
    return validated


def project_events(
    events: Iterable[Mapping[str, Any]],
    *,
    base_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply events through the one authoritative projection/validation path.

    ``base_snapshot`` is admitted only by the checkpoint loader below.  It lets
    normal appends apply a bounded delta without maintaining a second reducer.
    Full replay calls this function without a base and therefore exercises the
    exact same event semantics.
    """

    incoming = list(islice(iter(events), MAX_EVENTS + 1))
    if len(incoming) > MAX_EVENTS:
        raise ValueError("operational gap ledger exceeds its event bound")
    if base_snapshot is None:
        cards: dict[str, dict[str, Any]] = {}
        surfaces: dict[str, dict[str, Any]] = {}
        surface_aliases: dict[str, str] = {}
        reports: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        checkpoints: list[dict[str, Any]] = []
        work_admissions: list[dict[str, Any]] = []
        expected_inventory: dict[str, Any] | None = None
        expected_inventory_history: list[dict[str, Any]] = []
        previous_hash: str | None = None
        event_count = 0
        ledger_id: str | None = None
        last_timestamp: str | None = None
        first_timestamp: str | None = None
        transition_admission_backfills: list[dict[str, Any]] = []
    else:
        if base_snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
            raise ValueError("incremental projection base schema is invalid")
        event_count = int(base_snapshot.get("event_count") or 0)
        previous_hash = base_snapshot.get("head_event_sha256")
        if previous_hash is not None and not SHA256_PATTERN.fullmatch(str(previous_hash)):
            raise ValueError("incremental projection base head is invalid")
        ledger_id = base_snapshot.get("ledger_id")
        if event_count and (not isinstance(ledger_id, str) or not ledger_id):
            raise ValueError("incremental projection base ledger identity is invalid")
        cards = json.loads(_canonical(base_snapshot.get("cards", {})))
        surfaces = json.loads(_canonical(base_snapshot.get("surfaces", {})))
        surface_aliases = json.loads(_canonical(base_snapshot.get("surface_aliases", {})))
        reports = json.loads(_canonical(base_snapshot.get("reports", {})))
        relationships = json.loads(_canonical(base_snapshot.get("card_relationships", [])))
        checkpoints = json.loads(_canonical(base_snapshot.get("work_checkpoints", [])))
        work_admissions = json.loads(_canonical(base_snapshot.get("work_admissions", [])))
        expected_inventory = json.loads(_canonical(base_snapshot.get("expected_inventory")))
        expected_inventory_history = json.loads(
            _canonical(base_snapshot.get("expected_inventory_history", []))
        )
        last_timestamp = base_snapshot.get("generated_utc")
        first_timestamp = base_snapshot.get("created_utc")
        transition_admission_backfills = json.loads(
            _canonical(base_snapshot.get("transition_admission_backfills", []))
        )
        for card in cards.values():
            card.pop("canonical_surface", None)
            card.pop("linked_controls", None)
            card.pop("control_resolution", None)
            card.setdefault("control_scope_disposition", None)
            card.setdefault("control_scope_history", [])
            card.setdefault("evidence_attestations", [])
        for surface in surfaces.values():
            surface["examined"] = False
            surface["examined_controls"] = []
    start_sequence = event_count + 1
    if event_count + len(incoming) > MAX_EVENTS:
        raise ValueError("operational gap ledger exceeds its event bound")
    admission_backfills = _validated_transition_admission_backfills(
        incoming,
        start_sequence=start_sequence,
        previous_hash=previous_hash,
        allow_historical_targets=base_snapshot is None,
    )
    for sequence, original in enumerate(incoming, start_sequence):
        event_count += 1
        event = dict(original)
        last_timestamp = str(event["timestamp"])
        if first_timestamp is None:
            first_timestamp = last_timestamp
        kind = str(event["event_type"])
        payload = event.get("payload")
        assert isinstance(payload, Mapping)
        if kind == "ledger_initialized":
            if ledger_id is not None or sequence != 1:
                raise ValueError("ledger initialization must be the first and only initialization event")
            ledger_id = str(payload.get("ledger_id") or "")
            _nonempty(ledger_id, "ledger_id")
        elif kind in {"expected_inventory_registered", "expected_inventory_revised"}:
            if ledger_id is None:
                raise ValueError("expected inventory precedes ledger initialization")
            if kind == "expected_inventory_registered" and expected_inventory is not None:
                raise ValueError("expected inventory was registered more than once")
            if kind == "expected_inventory_revised" and expected_inventory is None:
                raise ValueError("expected inventory revision precedes registration")
            if kind == "expected_inventory_revised" and str(payload.get("previous_source_sha256") or "").lower() != expected_inventory["source_sha256"]:
                raise ValueError("expected inventory revision does not bind its predecessor")
            inventory_id = str(payload.get("inventory_id") or "").strip()
            source = str(payload.get("source") or "").strip()
            source_sha256 = str(payload.get("source_sha256") or "").lower()
            expected = payload.get("surfaces")
            _nonempty(inventory_id, "inventory_id")
            _nonempty(source, "source")
            if not SHA256_PATTERN.fullmatch(source_sha256):
                raise ValueError("expected inventory source_sha256 is invalid")
            if not isinstance(expected, list) or not expected:
                raise ValueError("expected inventory surfaces must be a non-empty array")
            ids: set[str] = set()
            normalized: list[dict[str, Any]] = []
            for item in expected:
                if not isinstance(item, Mapping):
                    raise ValueError("expected surface entry must be an object")
                surface_id = str(item.get("surface_id") or "").strip()
                count = item.get("expected_control_count")
                controls_sha256 = str(item.get("expected_controls_sha256") or "").lower()
                if not surface_id or surface_id in ids or not isinstance(count, int) or count < 0 or not SHA256_PATTERN.fullmatch(controls_sha256):
                    raise ValueError("expected surface entry is invalid or duplicated")
                ids.add(surface_id)
                normalized.append({"surface_id": surface_id, "expected_control_count": count, "expected_controls_sha256": controls_sha256})
            revised = {
                "inventory_id": inventory_id, "source": source,
                "source_sha256": source_sha256, "surfaces": normalized,
                "timestamp": event["timestamp"],
            }
            if expected_inventory is not None:
                expected_inventory_history.append(expected_inventory)
            expected_inventory = revised
        elif ledger_id is None:
            raise ValueError("ledger event precedes initialization")
        elif kind == "surface_registered":
            surface_id = str(payload.get("surface_id") or "")
            _nonempty(surface_id, "surface_id")
            if surface_id in surfaces:
                raise ValueError(f"surface {surface_id} was registered more than once")
            controls = payload.get("known_controls")
            if not isinstance(controls, list) or len(controls) != len(set(map(str, controls))):
                raise ValueError("known_controls must be a unique array")
            surfaces[surface_id] = {
                **json.loads(_canonical(dict(payload))), "examined": False,
                "examinations": [], "examined_controls": [],
                "control_dispositions": {}, "control_records": {},
                "inventory_revisions": [], "retired_controls": {},
            }
        elif kind == "surface_alias_registered":
            alias = str(payload.get("alias") or "").strip()
            surface_id = str(payload.get("surface_id") or "").strip()
            _nonempty(alias, "alias")
            if surface_id not in surfaces:
                raise ValueError(f"surface alias target is not registered: {surface_id}")
            if alias in surfaces or alias in surface_aliases:
                raise ValueError(f"surface alias is already assigned: {alias}")
            surface_aliases[alias] = surface_id
        elif kind == "surface_controls_added":
            surface_id = str(payload.get("surface_id") or "")
            controls = payload.get("controls")
            if surface_id not in surfaces:
                raise ValueError(f"controls added to unknown surface: {surface_id}")
            _evidence(payload.get("evidence"))
            existing = set(map(str, surfaces[surface_id]["known_controls"]))
            if surfaces[surface_id].get("control_records"):
                added, records = _validate_control_records(controls)
                if any(control in existing for control in added):
                    raise ValueError("added typed control is already registered")
                surfaces[surface_id]["known_controls"] = sorted(existing | set(added))
                surfaces[surface_id]["control_records"].update(records)
                surfaces[surface_id]["control_records"] = {
                    key: surfaces[surface_id]["control_records"][key]
                    for key in sorted(surfaces[surface_id]["control_records"])
                }
            else:
                if not isinstance(controls, list) or not controls or len(controls) != len(set(map(str, controls))):
                    raise ValueError("added controls must be a non-empty unique array")
                if any(not str(control).strip() or str(control) in existing for control in controls):
                    raise ValueError("added control is empty or already registered")
                surfaces[surface_id]["known_controls"] = sorted(existing | set(map(str, controls)))
        elif kind == "surface_inventory_revised":
            surface_id = str(payload.get("surface_id") or "")
            if surface_id not in surfaces:
                raise ValueError(f"inventory revision references unknown surface: {surface_id}")
            current = surfaces[surface_id]
            current.setdefault("retired_controls", {})
            previous_controls_sha256 = str(payload.get("previous_controls_sha256") or "").lower()
            current_controls = list(map(str, current["known_controls"]))
            previous_control_records = dict(current.get("control_records", {}))
            if previous_controls_sha256 != _controls_sha256(current_controls):
                raise ValueError("surface inventory revision does not bind its predecessor")
            controls, records = _validate_control_records(payload.get("controls"))
            removed_controls = set(current_controls) - set(controls)
            declared_retirement_schema = "retired_controls" in payload
            retirement_rows = payload.get("retired_controls", [])
            if not isinstance(retirement_rows, list) or any(
                not isinstance(item, Mapping) for item in retirement_rows
            ):
                raise ValueError("retired_controls must be an array of objects")
            retirement_ids = [str(item.get("control_id") or "") for item in retirement_rows]
            if declared_retirement_schema and (
                len(retirement_ids) != len(set(retirement_ids))
                or set(retirement_ids) != removed_controls
            ):
                raise ValueError("retired_controls must match the exact removed control set")
            if not declared_retirement_schema:
                retirement_rows = [
                    {
                        "control_id": control_id,
                        "reason": "Legacy pre-retirement-schema inventory revision.",
                        "replacement_control_ids": [],
                    }
                    for control_id in sorted(removed_controls)
                ]
            normalized_retirements: dict[str, dict[str, object]] = {}
            for item in retirement_rows:
                control_id = str(item.get("control_id") or "")
                reason = str(item.get("reason") or "").strip()
                replacements = item.get("replacement_control_ids", [])
                _nonempty(reason, "retired control reason")
                if (
                    not isinstance(replacements, list)
                    or len(replacements) != len(set(map(str, replacements)))
                    or any(str(replacement) not in controls for replacement in replacements)
                ):
                    raise ValueError("retired control replacements must reference unique current controls")
                if control_id in current["retired_controls"]:
                    raise ValueError("control was already retired")
                normalized_retirements[control_id] = {
                    "reason": reason,
                    "replacement_control_ids": sorted(map(str, replacements)),
                }
            reason = str(payload.get("reason") or "").strip()
            _nonempty(reason, "reason")
            evidence = _evidence(payload.get("evidence"))
            source_files = payload.get("source_files", current.get("source_files", []))
            if not isinstance(source_files, list) or not source_files or any(not isinstance(path, str) or not path.strip() for path in source_files):
                raise ValueError("surface inventory revision requires source_files")
            current["inventory_revisions"].append(
                {
                    "previous_controls_sha256": previous_controls_sha256,
                    "previous_known_controls": current_controls,
                    "retired_control_ids": sorted(removed_controls),
                    "retirement_schema": (
                        "current_declared" if declared_retirement_schema
                        else "legacy_inferred"
                    ),
                    "reason": reason,
                    "evidence": evidence,
                    "timestamp": event["timestamp"],
                    "actor": event["actor"],
                }
            )
            current["known_controls"] = controls
            current["control_records"] = records
            current["source_files"] = list(source_files)
            for control_id, retirement in normalized_retirements.items():
                current["retired_controls"][control_id] = {
                    "control_id": control_id,
                    "control_record": previous_control_records.get(control_id),
                    "disposition": current["control_dispositions"].pop(control_id, None),
                    **retirement,
                    "retired_at": event["timestamp"],
                    "retired_by": event["actor"],
                }
            current["retired_controls"] = {
                key: current["retired_controls"][key]
                for key in sorted(current["retired_controls"])
            }
            if set(current_controls) != set(controls):
                current["examined"] = False
                current["examined_controls"] = sorted(
                    set(map(str, current.get("examined_controls", []))) & set(controls)
                )
        elif kind == "control_disposition":
            surface_id = str(payload.get("surface_id") or "")
            control_id = str(payload.get("control_id") or "")
            if surface_id not in surfaces:
                raise ValueError(f"control disposition references unknown surface: {surface_id}")
            if control_id not in surfaces[surface_id]["known_controls"]:
                raise ValueError(f"control disposition references unknown control: {surface_id}/{control_id}")
            if control_id in surfaces[surface_id]["control_dispositions"]:
                raise ValueError(f"control already has a disposition: {surface_id}/{control_id}")
            disposition = str(payload.get("disposition") or "")
            if disposition not in {"operational", "gap"}:
                raise ValueError("control disposition must be operational or gap")
            evidence = _evidence(payload.get("evidence"))
            gap_ids = payload.get("gap_ids", [])
            if not isinstance(gap_ids, list) or any(str(gap_id) not in cards for gap_id in gap_ids):
                raise ValueError("control disposition gap_ids must reference known cards")
            if disposition == "gap" and not gap_ids:
                raise ValueError("gap control disposition requires at least one gap_id")
            if disposition == "operational" and gap_ids:
                raise ValueError("operational control disposition cannot reference gap_ids")
            observation = payload.get("observation")
            validated_observation = (
                _validate_control_observation(
                    observation,
                    disposition=disposition,
                    expected_kind=(
                        str(surfaces[surface_id]["control_records"][control_id]["kind"])
                        if control_id in surfaces[surface_id]["control_records"] else None
                    ),
                )
                if observation is not None else None
            )
            surfaces[surface_id]["control_dispositions"][control_id] = {
                "disposition": disposition,
                "gap_ids": list(map(str, gap_ids)),
                "evidence": evidence,
                "observation": validated_observation,
                "proof_status": "current_typed" if validated_observation else "legacy_unbound",
                "timestamp": event["timestamp"],
                "actor": event["actor"],
                "history": [],
            }
        elif kind == "control_disposition_revised":
            surface_id = str(payload.get("surface_id") or "")
            control_id = str(payload.get("control_id") or "")
            if surface_id not in surfaces or control_id not in surfaces[surface_id]["known_controls"]:
                raise ValueError("control disposition revision references an unknown surface/control")
            current = surfaces[surface_id]["control_dispositions"].get(control_id)
            if current is None:
                raise ValueError("control disposition revision requires an existing disposition")
            predecessor = str(payload.get("previous_disposition_sha256") or "").lower()
            if predecessor != control_disposition_sha256(current):
                raise ValueError("control disposition revision does not bind its predecessor")
            before = str(payload.get("from_disposition") or "")
            after = str(payload.get("to_disposition") or "")
            if before != current["disposition"] or after not in {"operational", "gap"}:
                raise ValueError("control disposition revision has an invalid transition")
            reason = str(payload.get("reason") or "").strip()
            _nonempty(reason, "reason")
            evidence = _evidence(payload.get("evidence"))
            gap_ids = payload.get("gap_ids", [])
            if not isinstance(gap_ids, list) or any(str(gap_id) not in cards for gap_id in gap_ids):
                raise ValueError("revised control disposition gap_ids must reference known cards")
            if after == "gap" and not gap_ids:
                raise ValueError("revised gap control disposition requires at least one gap_id")
            if after == "operational" and gap_ids:
                raise ValueError("revised operational control disposition cannot reference gap_ids")
            normalized_gap_ids = list(map(str, gap_ids))
            observation = payload.get("observation")
            validated_observation = (
                _validate_control_observation(
                    observation,
                    disposition=after,
                    expected_kind=(
                        str(surfaces[surface_id]["control_records"][control_id]["kind"])
                        if control_id in surfaces[surface_id]["control_records"] else None
                    ),
                )
                if observation is not None else None
            )
            if (
                after == before
                and normalized_gap_ids == list(current["gap_ids"])
                and validated_observation == current.get("observation")
            ):
                raise ValueError("control disposition revision is a semantic no-op")
            prior_history = list(current.get("history", []))
            prior_history.append({
                "disposition": current["disposition"],
                "gap_ids": list(current["gap_ids"]),
                "evidence": list(current["evidence"]),
                "timestamp": current["timestamp"],
                "actor": current["actor"],
                "superseded_at": event["timestamp"],
                "superseded_by": event["actor"],
                "revision_reason": reason,
                "disposition_sha256": predecessor,
            })
            surfaces[surface_id]["control_dispositions"][control_id] = {
                "disposition": after,
                "gap_ids": normalized_gap_ids,
                "evidence": evidence,
                "observation": validated_observation,
                "proof_status": "current_typed" if validated_observation else "legacy_unbound",
                "timestamp": event["timestamp"],
                "actor": event["actor"],
                "history": prior_history,
            }
        elif kind == "surface_examined":
            surface_id = str(payload.get("surface_id") or "")
            if surface_id not in surfaces:
                raise ValueError(f"unregistered surface examined: {surface_id}")
            evidence = _evidence(payload.get("evidence"))
            outcome = payload.get("outcome")
            if outcome not in {"operational", "gap"}:
                raise ValueError("surface examination outcome must be operational or gap")
            gap_ids = payload.get("gap_ids", [])
            if not isinstance(gap_ids, list) or (outcome == "gap" and not gap_ids):
                raise ValueError("gap surface examination requires gap_ids")
            if any(gap_id not in cards for gap_id in gap_ids):
                raise ValueError("surface examination references an unknown gap")
            examined_controls = payload.get("examined_controls", [])
            if not isinstance(examined_controls, list) or not examined_controls:
                raise ValueError("examined_controls must be an array")
            known = set(map(str, surfaces[surface_id]["known_controls"]))
            if any(str(control) not in known for control in examined_controls):
                raise ValueError("examined_controls contains a control not registered to the surface")
            row = {**dict(payload), "evidence": evidence, "timestamp": event["timestamp"]}
            surfaces[surface_id]["examinations"].append(row)
            surfaces[surface_id]["examined_controls"] = sorted(set(surfaces[surface_id]["examined_controls"]) | set(map(str, examined_controls)))
        elif kind == "card_discovered":
            card = _validate_card(payload, allow_local_discovery_empty_symbols=True)
            gap_id = card["gap_id"]
            if gap_id in cards:
                raise ValueError(f"stable gap ID was reused: {gap_id}")
            discovery_evidence = payload.get("discovery_evidence") or [{"reference": card["discovery_source"], "claim": card["observed_behavior"]}]
            card["discovery_event_id"] = event["event_id"]
            card["discovery_event_sha256"] = event["event_sha256"]
            card["discovery_sequence"] = event["sequence"]
            card["history"] = [{"event": "discovered", "timestamp": event["timestamp"], "actor": event["actor"], "event_id": event["event_id"], "event_sha256": event["event_sha256"], "sequence": event["sequence"], "evidence": _evidence(discovery_evidence, "discovery_evidence")}]
            card["annotations"] = []
            card["control_scope_disposition"] = None
            card["control_scope_history"] = []
            card["evidence_attestations"] = []
            cards[gap_id] = card
        elif kind == "card_annotated":
            gap_id = str(payload.get("gap_id") or "")
            if gap_id not in cards:
                raise ValueError(f"annotation references unknown card: {gap_id}")
            evidence = _evidence(payload.get("evidence"))
            note = str(payload.get("note") or "").strip()
            if not note:
                raise ValueError("card annotation requires a note")
            patch = payload.get("patch", {})
            allowed = {"source_refs", "interaction_chain", "dependencies", "blockers", "assigned_owner", "tests_required", "completion_evidence", "next_action", "operational_impact", "reopen_reason", "defer_skip"}
            if not isinstance(patch, Mapping) or set(patch) - allowed:
                raise ValueError("card annotation contains immutable or unknown fields")
            if "interaction_chain" in patch:
                patch = {**patch, "interaction_chain": _validate_chain(patch["interaction_chain"])}
            cards[gap_id].update(json.loads(_canonical(dict(patch))))
            _validate_current_card(cards[gap_id])
            annotation = {"event": "annotated", "timestamp": event["timestamp"], "actor": event["actor"], "note": note, "evidence": evidence, "patch": dict(patch)}
            cards[gap_id]["annotations"].append(annotation)
            cards[gap_id]["history"].append(annotation)
        elif kind == "card_transition":
            gap_id = str(payload.get("gap_id") or "")
            if gap_id not in cards:
                raise ValueError(f"transition references unknown card: {gap_id}")
            before = cards[gap_id]["current_state"]
            after = str(payload.get("to_state") or "")
            if payload.get("from_state") != before or not _transition_allowed(before, after):
                raise ValueError(f"invalid card transition {gap_id}: {before} -> {after}")
            effective_payload = dict(payload)
            attestation = admission_backfills.get(str(event["event_sha256"]))
            if attestation is not None:
                effective_payload.update(
                    json.loads(_canonical(attestation["admission"]))
                )
            _validate_transition_admission(cards[gap_id], effective_payload)
            evidence = _evidence(payload.get("evidence"))
            reason = str(payload.get("reason") or "").strip()
            if not reason:
                raise ValueError("card transition requires a reason")
            if after == "closed" and (
                not cards[gap_id].get("completion_evidence")
                or any(not isinstance(item, str) or not item.strip() for item in cards[gap_id]["completion_evidence"])
            ):
                raise ValueError("card cannot close without completion_evidence")
            if after == "reopened" and not str(payload.get("reopen_reason") or "").strip():
                raise ValueError("reopened transition requires reopen_reason")
            if after == "deferred":
                defer = payload.get("defer_skip")
                if not isinstance(defer, Mapping) or any(
                    not str(defer.get(field) or "").strip()
                    for field in ("reason", "authority", "dependency", "return_condition")
                ):
                    raise ValueError("deferred transition requires reason, authority, dependency, and return_condition")
                cards[gap_id]["defer_skip"] = dict(defer)
            if after == "reopened":
                cards[gap_id]["reopen_reason"] = str(payload["reopen_reason"])
            cards[gap_id]["current_state"] = after
            history_row = {"event": "transition", "from": before, "to": after, "timestamp": event["timestamp"], "actor": event["actor"], "event_id": event["event_id"], "event_sha256": event["event_sha256"], "sequence": event["sequence"], "reason": reason, "evidence": evidence}
            for field in (
                "implementation_evidence", "verification", "integration_evidence",
                "operational_evidence", "replacement_gap_id", "authority",
                "reopen_reason", "regression_strengthening", "defer_skip",
                "boundary_evidence",
                "contradicted_transition_event_sha256",
                "closure_evidence",
            ):
                if field in effective_payload:
                    history_row[field] = json.loads(_canonical(effective_payload[field]))
            if attestation is not None:
                history_row["admission_backfill"] = {
                    "finding_id": attestation["finding_id"],
                    "backfill_event_id": attestation["backfill_event_id"],
                    "target_event_sha256": event["event_sha256"],
                }
            cards[gap_id]["history"].append(history_row)
        elif kind == "transition_admission_backfilled":
            validated = [
                value for value in admission_backfills.values()
                if value["backfill_event_id"] == event["event_id"]
            ]
            if not validated:
                raise ValueError("transition admission backfill has no valid attestations")
            transition_admission_backfills.append(
                {
                    "event_id": event["event_id"],
                    "event_sha256": event["event_sha256"],
                    "finding_id": validated[0]["finding_id"],
                    "reason": str(payload["reason"]),
                    "evidence": _evidence(payload.get("evidence")),
                    "target_event_sha256s": sorted(admission_backfills_for_event["target_event_sha256"] for admission_backfills_for_event in validated),
                    "timestamp": event["timestamp"],
                    "actor": event["actor"],
                }
            )
        elif kind == "report_registered":
            report_id = str(payload.get("report_id") or "").strip()
            _nonempty(report_id, "report_id")
            if report_id in reports:
                raise ValueError(f"report was registered more than once: {report_id}")
            source = str(payload.get("source") or "").strip()
            source_sha256 = str(payload.get("source_sha256") or "").lower()
            finding_ids = payload.get("finding_ids")
            _nonempty(source, "source")
            if not SHA256_PATTERN.fullmatch(source_sha256):
                raise ValueError("report source_sha256 is invalid")
            if not isinstance(finding_ids, list) or not finding_ids or len(finding_ids) != len(set(map(str, finding_ids))):
                raise ValueError("report finding_ids must be a non-empty unique array")
            reports[report_id] = {
                **dict(payload), "finding_ids": list(map(str, finding_ids)),
                "reconciliations": {}, "timestamp": event["timestamp"],
            }
        elif kind == "report_finding_reconciled":
            report_id = str(payload.get("report_id") or "")
            finding_id = str(payload.get("finding_id") or "")
            if report_id not in reports or finding_id not in reports[report_id]["finding_ids"]:
                raise ValueError("report reconciliation references an unknown report finding")
            if finding_id in reports[report_id]["reconciliations"]:
                raise ValueError("report finding was reconciled more than once")
            disposition = str(payload.get("disposition") or "")
            if disposition not in {"card", "operational", "duplicate"}:
                raise ValueError("report reconciliation disposition is invalid")
            gap_ids = payload.get("gap_ids", [])
            if not isinstance(gap_ids, list) or any(str(gap_id) not in cards for gap_id in gap_ids):
                raise ValueError("report reconciliation references an unknown card")
            if disposition in {"card", "duplicate"} and not gap_ids:
                raise ValueError("card and duplicate dispositions require gap_ids")
            evidence = _evidence(payload.get("evidence"))
            reports[report_id]["reconciliations"][finding_id] = {
                "disposition": disposition, "gap_ids": list(map(str, gap_ids)),
                "evidence": evidence, "timestamp": event["timestamp"],
                "actor": event["actor"],
            }
        elif kind == "card_relationship":
            parent = str(payload.get("parent_gap_id") or "")
            child = str(payload.get("child_gap_id") or "")
            relation = str(payload.get("relationship") or "")
            if parent not in cards or child not in cards or parent == child:
                raise ValueError("card relationship requires two distinct known cards")
            if relation not in {"child", "blocks", "depends_on", "duplicates", "supersedes"}:
                raise ValueError("card relationship type is invalid")
            if any(
                item["parent_gap_id"] == parent
                and item["child_gap_id"] == child
                and item["relationship"] == relation
                for item in relationships
            ):
                raise ValueError("card relationship was already recorded")
            relationships.append({
                **dict(payload), "evidence": _evidence(payload.get("evidence")),
                "timestamp": event["timestamp"], "actor": event["actor"],
            })
        elif kind in {"card_control_scope_set", "card_control_scope_revised"}:
            gap_id = str(payload.get("gap_id") or "")
            validated = _validate_card_control_scope(cards, relationships, payload)
            current = cards[gap_id].get("control_scope_disposition")
            if kind == "card_control_scope_set":
                if current is not None:
                    raise ValueError("card control scope was already set")
                history: list[dict[str, Any]] = []
            else:
                if not isinstance(current, Mapping):
                    raise ValueError("card control scope revision requires a current disposition")
                predecessor = str(payload.get("previous_scope_sha256") or "")
                if predecessor != card_control_scope_sha256(current):
                    raise ValueError("card control scope revision predecessor is stale")
                history = list(cards[gap_id].get("control_scope_history", []))
                history.append({
                    **dict(current),
                    "scope_sha256": predecessor,
                    "superseded_at": event["timestamp"],
                    "superseded_by": event["actor"],
                })
            disposition = {
                **validated,
                "evidence": _evidence(payload.get("evidence")),
                "timestamp": event["timestamp"],
                "actor": event["actor"],
            }
            cards[gap_id]["control_scope_disposition"] = disposition
            cards[gap_id]["control_scope_history"] = history
        elif kind == "card_evidence_attested":
            gap_id = str(payload.get("gap_id") or "")
            if gap_id not in cards:
                raise ValueError("evidence attestation references an unknown card")
            target = str(payload.get("target_evidence_sha256") or "").lower()
            if not SHA256_PATTERN.fullmatch(target):
                raise ValueError("evidence attestation target is invalid")
            history_evidence = [
                item
                for row in cards[gap_id].get("history", [])
                for item in row.get("evidence", [])
            ]
            if target not in {evidence_reference_sha256(item) for item in history_evidence}:
                raise ValueError("evidence attestation target is not present on the card")
            artifact_sha256 = str(payload.get("artifact_sha256") or "").lower()
            artifact_size = payload.get("artifact_size")
            method = str(payload.get("verification_method") or "").strip()
            if (
                not SHA256_PATTERN.fullmatch(artifact_sha256)
                or not isinstance(artifact_size, int)
                or artifact_size < 0
                or not method
            ):
                raise ValueError("evidence attestation requires artifact hash, size, and method")
            existing = cards[gap_id].setdefault("evidence_attestations", [])
            if any(item["target_evidence_sha256"] == target for item in existing):
                raise ValueError("evidence attestation was already recorded")
            existing.append({
                "target_evidence_sha256": target,
                "artifact_sha256": artifact_sha256,
                "artifact_size": artifact_size,
                "verification_method": method,
                "evidence": _evidence(payload.get("evidence")),
                "timestamp": event["timestamp"],
                "actor": event["actor"],
                "event_id": event["event_id"],
                "event_sha256": event["event_sha256"],
            })
        elif kind == "work_checkpoint":
            active_gap_id = str(payload.get("active_gap_id") or "")
            if active_gap_id not in cards:
                raise ValueError("work checkpoint references an unknown active card")
            learned = str(payload.get("learned") or "").strip()
            next_action = str(payload.get("next_action") or "").strip()
            unresolved = payload.get("unresolved_branch_gap_ids", [])
            if not learned or not next_action or not isinstance(unresolved, list) or any(str(gap_id) not in cards for gap_id in unresolved):
                raise ValueError("work checkpoint requires learned, next_action, and known unresolved branches")
            checkpoints.append({
                **dict(payload), "unresolved_branch_gap_ids": list(map(str, unresolved)),
                "newly_discovered_gap_ids": list(map(str, payload.get("newly_discovered_gap_ids", []))),
                "evidence": _evidence(payload.get("evidence")),
                "timestamp": event["timestamp"], "actor": event["actor"],
                "event_id": event["event_id"], "event_sha256": event["event_sha256"],
                "sequence": event["sequence"],
            })
        elif kind == "work_admitted":
            if not checkpoints:
                raise ValueError("work admission requires an active checkpoint")
            active = checkpoints[-1]
            gap_id = str(payload.get("gap_id") or "")
            if gap_id not in cards or cards[gap_id]["current_state"] == "closed":
                raise ValueError("work admission requires a known non-closed card")
            if gap_id != active["active_gap_id"] or payload.get("checkpoint_event_id") != active.get("event_id"):
                raise ValueError("work admission does not bind the active checkpoint")
            effect = str(payload.get("effect") or "")
            if effect not in {"read", "write", "execute", "network", "install", "service", "destructive"}:
                raise ValueError("work admission effect is invalid")
            scope = payload.get("scope")
            authority = str(payload.get("authority") or "").strip()
            expected_effect = str(payload.get("expected_effect") or "").strip()
            rollback = str(payload.get("rollback") or "").strip()
            if not isinstance(scope, list) or not scope or any(not isinstance(item, str) or not item.strip() for item in scope):
                raise ValueError("work admission requires a non-empty exact scope")
            if not authority or not expected_effect or not rollback:
                raise ValueError("work admission requires authority, expected_effect, and rollback")
            work_admissions.append({
                **dict(payload), "scope": list(scope),
                "evidence": _evidence(payload.get("evidence")),
                "timestamp": event["timestamp"], "actor": event["actor"],
                "event_id": event["event_id"], "event_sha256": event["event_sha256"],
            })
        previous_hash = str(event["event_sha256"])
    if event_count and ledger_id is None:
        raise ValueError("ledger is not initialized")
    state_counts = Counter(card["current_state"] for card in cards.values())
    lacking_evidence = []
    unbound_evidence: list[str] = []
    for gap_id, card in cards.items():
        card.setdefault("control_scope_disposition", None)
        card.setdefault("control_scope_history", [])
        card.setdefault("evidence_attestations", [])
        history = card.get("history", [])
        chain_lacks = any(
            item["state"] in {"present", "partial"} and not item.get("evidence")
            for item in card["interaction_chain"].values()
        )
        if not history or chain_lacks or any(not row.get("evidence") for row in history if row.get("event") in {"discovered", "transition"}) or (card["current_state"] == "closed" and not card.get("completion_evidence")):
            lacking_evidence.append(gap_id)
        history_evidence = [evidence for row in history for evidence in row.get("evidence", [])]
        attested = {
            str(item.get("target_evidence_sha256") or "")
            for item in card.get("evidence_attestations", [])
        }
        if any(
            "artifact_sha256" not in evidence
            and "#sha256=" not in str(evidence.get("reference", ""))
            and not str(evidence.get("reference", "")).startswith("sha256:")
            and evidence_reference_sha256(evidence) not in attested
            for evidence in history_evidence
        ):
            unbound_evidence.append(gap_id)
    for card in cards.values():
        canonical_surface = card["parent_surface"] if card["parent_surface"] in surfaces else surface_aliases.get(card["parent_surface"])
        card["canonical_surface"] = canonical_surface
        card["linked_controls"] = []
    for surface_id, surface in surfaces.items():
        for control_id, disposition in surface["control_dispositions"].items():
            for gap_id in disposition["gap_ids"]:
                cards[gap_id]["linked_controls"].append({"surface_id": surface_id, "control_id": control_id})
        known = set(map(str, surface["known_controls"]))
        disposed = set(surface["control_dispositions"])
        observed = {
            control_id for control_id, disposition in surface["control_dispositions"].items()
            if disposition.get("proof_status") == "current_typed"
        }
        operationally_proven = {
            control_id for control_id, disposition in surface["control_dispositions"].items()
            if disposition.get("proof_status") == "current_typed"
            and disposition.get("disposition") == "operational"
        }
        surface["inventory_reconciled"] = bool(known) and known == disposed
        surface["examined"] = bool(known) and known == observed
        surface["operationally_proven"] = bool(known) and known == operationally_proven
        surface["examined_controls"] = sorted(observed)
    control_scope_conflicts: list[str] = []
    for gap_id, card in cards.items():
        explicit = card.get("control_scope_disposition")
        if card["linked_controls"]:
            card["control_resolution"] = {
                "kind": "typed_controls",
                "resolved": True,
                "bindings": sorted(
                    card["linked_controls"],
                    key=lambda item: (item["surface_id"], item["control_id"]),
                ),
            }
            if explicit is not None and explicit.get("kind") != "typed_controls":
                card["control_resolution"]["explicit_scope_conflict"] = True
                control_scope_conflicts.append(gap_id)
            elif isinstance(explicit, Mapping):
                card["control_resolution"]["scope_revision"] = dict(explicit)
        elif isinstance(explicit, Mapping) and explicit.get("kind") == "non_visible_path":
            card["control_resolution"] = {
                **dict(explicit),
                "resolved": True,
            }
        elif isinstance(explicit, Mapping) and explicit.get("kind") == "aggregate_parent":
            card["control_resolution"] = {
                **dict(explicit),
                "resolved": False,
                "unresolved_child_gap_ids": list(explicit.get("child_gap_ids", [])),
            }
        elif isinstance(explicit, Mapping) and explicit.get("kind") == "typed_controls":
            card["control_resolution"] = {
                **dict(explicit),
                "resolved": False,
                "unresolved_reason": "typed controls are not yet dispositioned to this card",
            }
        else:
            card["control_resolution"] = {"kind": "unresolved", "resolved": False}
    for _ in range(len(cards)):
        changed = False
        for card in cards.values():
            resolution = card["control_resolution"]
            if resolution.get("kind") != "aggregate_parent" or resolution.get("resolved"):
                continue
            children = list(resolution.get("child_gap_ids", []))
            unresolved = [child for child in children if not cards[child]["control_resolution"].get("resolved")]
            resolution["unresolved_child_gap_ids"] = unresolved
            if not unresolved:
                resolution["resolved"] = True
                changed = True
        if not changed:
            break
    total_controls = sum(len(surface.get("known_controls", [])) for surface in surfaces.values())
    disposed_controls = sum(len(surface.get("control_dispositions", {})) for surface in surfaces.values())
    examined_controls = sum(len(surface.get("examined_controls", [])) for surface in surfaces.values())
    operational_controls = sum(
        sum(
            1 for item in surface["control_dispositions"].values()
            if item["disposition"] == "operational"
            and item.get("proof_status") == "current_typed"
        )
        for surface in surfaces.values()
    )
    gap_controls = sum(sum(1 for item in surface["control_dispositions"].values() if item["disposition"] == "gap") for surface in surfaces.values())
    report_finding_count = sum(len(report["finding_ids"]) for report in reports.values())
    report_reconciled_count = sum(len(report["reconciliations"]) for report in reports.values())
    unreconciled_report_findings = sorted(
        f"{report_id}/{finding_id}"
        for report_id, report in reports.items()
        for finding_id in report["finding_ids"]
        if finding_id not in report["reconciliations"]
    )
    expected_rows = {item["surface_id"]: item for item in (expected_inventory or {}).get("surfaces", [])}
    expected_missing = sorted(set(expected_rows) - set(surfaces))
    unexpected_registered = sorted(set(surfaces) - set(expected_rows)) if expected_inventory else []
    inventory_drift: list[str] = []
    for surface_id in set(expected_rows) & set(surfaces):
        controls_json = json.dumps(surfaces[surface_id]["known_controls"], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        row = expected_rows[surface_id]
        if len(surfaces[surface_id]["known_controls"]) != row["expected_control_count"] or hashlib.sha256(controls_json).hexdigest() != row["expected_controls_sha256"]:
            inventory_drift.append(surface_id)
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "ledger_id": ledger_id,
        "event_count": event_count,
        "head_event_sha256": previous_hash,
        "generated_utc": last_timestamp,
        "created_utc": first_timestamp,
        "states": list(PRIMARY_STATES + NON_TERMINAL_STATES),
        "state_counts": {state: state_counts.get(state, 0) for state in PRIMARY_STATES + NON_TERMINAL_STATES},
        "surface_aliases": {key: surface_aliases[key] for key in sorted(surface_aliases)},
        "expected_inventory": expected_inventory,
        "expected_inventory_history": expected_inventory_history,
        "progress": {
            "surfaces_inventoried": len(surfaces),
            "total_known_surfaces": len(expected_rows) if expected_inventory else None,
            "expected_surfaces_missing": expected_missing,
            "unexpected_registered_surfaces": unexpected_registered,
            "inventory_drift_surfaces": sorted(inventory_drift),
            "surfaces_examined": sum(1 for item in surfaces.values() if item["examined"]),
            "surfaces_not_yet_examined": sorted(key for key, item in surfaces.items() if not item["examined"]),
            "surfaces_inventory_reconciled": sum(
                1 for item in surfaces.values() if item.get("inventory_reconciled")
            ),
            "surfaces_operationally_proven": sum(
                1 for item in surfaces.values() if item.get("operationally_proven")
            ),
            "known_controls": total_controls,
            "examined_controls": examined_controls,
            "controls_with_disposition": disposed_controls,
            "controls_with_current_observation": examined_controls,
            "controls_not_yet_disposed": total_controls - disposed_controls,
            "controls_without_current_observation": total_controls - examined_controls,
            "operational_controls": operational_controls,
            "gap_controls": gap_controls,
            "gaps_discovered": len(cards),
            **{state: state_counts.get(state, 0) for state in PRIMARY_STATES + NON_TERMINAL_STATES},
            "unassigned": sum(1 for card in cards.values() if card.get("assigned_owner") in {"unassigned", "unknown"}),
            "cards_lacking_required_evidence": sorted(lacking_evidence),
            "cards_with_unbound_evidence": sorted(unbound_evidence),
            "evidence_deficient_cards": sorted(set(lacking_evidence) | set(unbound_evidence)),
            "cards_missing_source_symbols": sorted(
                gap_id for gap_id, card in cards.items()
                if any(not ref.get("symbols") for ref in card.get("source_refs", []))
            ),
            "cards_with_unregistered_surface": sorted(gap_id for gap_id, card in cards.items() if card["canonical_surface"] is None),
            "cards_without_control_links": sorted(gap_id for gap_id, card in cards.items() if not card["linked_controls"]),
            "cards_without_control_resolution": sorted(
                gap_id for gap_id, card in cards.items()
                if not card["control_resolution"].get("resolved")
            ),
            "card_control_scope_conflicts": sorted(control_scope_conflicts),
            "typed_control_cards": sum(
                1 for card in cards.values()
                if card["control_resolution"].get("kind") == "typed_controls"
            ),
            "aggregate_parent_cards": sum(
                1 for card in cards.values()
                if card["control_resolution"].get("kind") == "aggregate_parent"
            ),
            "non_visible_path_cards": sum(
                1 for card in cards.values()
                if card["control_resolution"].get("kind") == "non_visible_path"
            ),
            "reports_registered": len(reports),
            "report_findings": report_finding_count,
            "report_findings_reconciled": report_reconciled_count,
            "unreconciled_report_findings": unreconciled_report_findings,
        },
        "surfaces": {key: surfaces[key] for key in sorted(surfaces)},
        "cards": {key: cards[key] for key in sorted(cards)},
        "reports": {key: reports[key] for key in sorted(reports)},
        "card_relationships": relationships,
        "work_checkpoints": checkpoints,
        "work_admissions": work_admissions,
        "transition_admission_backfills": transition_admission_backfills,
    }


def validate(root: Path) -> dict[str, Any]:
    events = read_events(root)
    snapshot = project_events(events)
    return {"valid": True, "event_count": len(events), "head_event_sha256": snapshot["head_event_sha256"], "progress": snapshot["progress"]}


def _write_bytes_atomically(target: Path, data: bytes) -> None:
    prepared = target.with_name(f".{target.name}.{uuid4().hex}.prepared")
    try:
        with prepared.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(prepared, target)
        if hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(str(target.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        prepared.unlink(missing_ok=True)


def _encoded_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8") + b"\n"


def _seal_snapshot(
    snapshot: Mapping[str, Any], *, ledger_size_bytes: int
) -> tuple[dict[str, Any], bytes]:
    sealed = json.loads(_canonical(dict(snapshot)))
    sealed.pop("projection_sha256", None)
    sealed.pop("ledger_size_bytes", None)
    sealed["ledger_size_bytes"] = ledger_size_bytes
    sealed["projection_sha256"] = _digest(sealed)
    encoded = _encoded_json(sealed)
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("operational gap ledger snapshot byte bound would be exceeded")
    return sealed, encoded


def _write_snapshot_unlocked(
    root: Path,
    snapshot: Mapping[str, Any],
    ledger_size_bytes: int | None = None,
) -> dict[str, Any]:
    target = _inside(root, root / SNAPSHOT_RELATIVE)
    target.parent.mkdir(parents=True, exist_ok=True)
    ledger = _inside(root, root / LEDGER_RELATIVE)
    size = (
        int(ledger_size_bytes)
        if ledger_size_bytes is not None
        else (ledger.stat().st_size if ledger.exists() else 0)
    )
    sealed, encoded = _seal_snapshot(snapshot, ledger_size_bytes=size)
    _write_bytes_atomically(target, encoded)
    return sealed


def _bounded_progress(progress: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in progress.items():
        if isinstance(value, list):
            result[key] = value[:25]
            result[f"{key}_count"] = len(value)
            result[f"{key}_truncated"] = len(value) > 25
        else:
            result[key] = value
    return result


def _dashboard_index(snapshot: Mapping[str, Any], *, limit: int = 100) -> dict[str, Any]:
    cards = [
        item for item in snapshot.get("cards", {}).values()
        if isinstance(item, Mapping)
    ]
    priority = {"blocker": 0, "critical": 1, "high": 2, "medium": 3, "low": 4}
    cards.sort(
        key=lambda item: (
            item.get("current_state") == "closed",
            priority.get(str(item.get("severity") or "low"), 9),
            str(item.get("gap_id") or ""),
        )
    )
    lacking = set(snapshot.get("progress", {}).get("cards_lacking_required_evidence", []))
    def clipped(value: object, maximum: int) -> str:
        text = str(value or "")
        return text if len(text) <= maximum else text[: maximum - 1] + "…"

    rows = [
        {
            "id": clipped(item.get("gap_id") or "unknown", 96),
            "severity": clipped(item.get("severity") or "unknown", 32).lower(),
            "area": clipped(item.get("parent_surface") or "unclassified", 160),
            "feature": clipped(item.get("feature") or "unclassified", 240),
            "control_action": clipped(item.get("control_action") or "unknown", 240),
            "status": str(item.get("current_state") or "discovered"),
            "finding": clipped(item.get("observed_behavior") or "No observation retained.", 1200),
            "acceptance": clipped(item.get("expected_behavior") or "No expected behavior retained.", 1200),
            "next_action": clipped(item.get("next_action"), 800),
            "assigned_owner": clipped(item.get("assigned_owner"), 160),
            "canonical_surface": clipped(item.get("canonical_surface"), 160),
            "linked_control_count": len(item.get("linked_controls", [])),
            "evidence_lacking": str(item.get("gap_id") or "") in lacking,
        }
        for item in cards[:limit]
    ]
    state_counts = dict(snapshot.get("state_counts", {}))
    return {
        "count": len(cards),
        "open_count": sum(1 for item in cards if item.get("current_state") != "closed"),
        "status_counts": state_counts,
        "progress": _bounded_progress(snapshot.get("progress", {})),
        "cards": rows,
        "limit": limit,
        "truncated": len(cards) > len(rows),
    }


def _ledger_fingerprint(root: Path) -> dict[str, int]:
    path = _inside(root, root / LEDGER_RELATIVE)
    if not path.exists():
        return {"device": 0, "inode": 0, "size_bytes": 0, "mtime_ns": 0}
    value = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(value.st_mode) or value.st_size > MAX_LEDGER_BYTES:
        raise ValueError("operational gap ledger is not a bounded physical file")
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "size_bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
    }


def _maximum_gap_ordinal(snapshot: Mapping[str, Any]) -> int:
    highest = 0
    for gap_id in snapshot.get("cards", {}):
        match = re.fullmatch(r"PX-OS-([0-9]+)", str(gap_id))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def _build_head(
    snapshot: Mapping[str, Any],
    snapshot_bytes: bytes,
    *,
    fingerprint: Mapping[str, int],
    tail_event: Mapping[str, Any] | None,
    verification_basis: Mapping[str, Any],
    previous_checkpoint_sha256: str | None,
) -> tuple[dict[str, Any], bytes]:
    body: dict[str, Any] = {
        "schema_version": HEAD_SCHEMA,
        "ledger_id": snapshot.get("ledger_id"),
        "event_count": snapshot.get("event_count"),
        "head_event_sha256": snapshot.get("head_event_sha256"),
        "predecessor_event_sha256": (
            tail_event.get("previous_event_sha256") if tail_event else None
        ),
        "ledger_fingerprint": dict(fingerprint),
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "snapshot_size_bytes": len(snapshot_bytes),
        "maximum_gap_ordinal": _maximum_gap_ordinal(snapshot),
        "created_utc": snapshot.get("created_utc"),
        "generated_utc": snapshot.get("generated_utc"),
        "verification_basis": dict(verification_basis),
        "previous_checkpoint_sha256": previous_checkpoint_sha256,
        "dashboard": _dashboard_index(snapshot),
    }
    body["checkpoint_sha256"] = _digest(body)
    encoded = _encoded_json(body)
    if len(encoded) > MAX_HEAD_BYTES:
        raise ValueError("operational gap ledger compact head byte bound would be exceeded")
    return body, encoded


def _last_event_unlocked(root: Path) -> dict[str, Any] | None:
    path = _inside(root, root / LEDGER_RELATIVE)
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_LEDGER_BYTES:
            raise ValueError("operational ledger tail source exceeds its physical-file bound")
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        position = end
        buffer = b""
        while position > 0 and b"\n" not in buffer.rstrip(b"\n"):
            size = min(8192, position)
            position -= size
            handle.seek(position)
            buffer = handle.read(size) + buffer
            if len(buffer) > MAX_EVENT_BYTES:
                raise ValueError("operational ledger final event exceeds its bound")
    lines = [line for line in buffer.splitlines() if line.strip()]
    if not lines:
        return None
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise ValueError("operational ledger final event is not an object")
    return value


def _decode_head(data: bytes) -> dict[str, Any]:
    if not data or len(data) > MAX_HEAD_BYTES:
        raise ValueError("operational gap ledger compact head is missing or unbounded")
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("schema_version") != HEAD_SCHEMA:
        raise ValueError("operational gap ledger compact head schema is invalid")
    claimed = str(value.get("checkpoint_sha256") or "")
    body = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    if not SHA256_PATTERN.fullmatch(claimed) or _digest(body) != claimed:
        raise ValueError("operational gap ledger compact head hash is invalid")
    basis = value.get("verification_basis")
    if not isinstance(basis, Mapping) or basis.get("kind") not in {
        "full_replay", "incremental_from_verified_checkpoint"
    }:
        raise ValueError("operational gap ledger checkpoint basis is invalid")
    previous = value.get("previous_checkpoint_sha256")
    if basis.get("kind") == "incremental_from_verified_checkpoint" and (
        not isinstance(previous, str) or not SHA256_PATTERN.fullmatch(previous)
    ):
        raise ValueError("incremental checkpoint is not predecessor-bound")
    return value


def _read_checkpoint_once(
    root: Path, *, include_snapshot: bool
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    head_path = _inside(root, root / HEAD_RELATIVE)
    head_a_bytes = _read_bounded_regular(
        head_path, MAX_HEAD_BYTES, "operational gap ledger compact head"
    )
    head = _decode_head(head_a_bytes)
    if head.get("ledger_fingerprint") != _ledger_fingerprint(root):
        raise ValueError("operational gap ledger checkpoint fingerprint is stale")
    tail = _last_event_unlocked(root)
    if tail is None:
        if head.get("event_count") != 0 or head.get("head_event_sha256") is not None:
            raise ValueError("operational gap ledger checkpoint empty head is invalid")
    elif (
        tail.get("sequence") != head.get("event_count")
        or tail.get("event_sha256") != head.get("head_event_sha256")
        or tail.get("previous_event_sha256") != head.get("predecessor_event_sha256")
        or tail.get("event_sha256") != _digest(_event_body(tail))
    ):
        raise ValueError("operational gap ledger checkpoint does not match its tail")
    snapshot: dict[str, Any] | None = None
    if include_snapshot:
        target = _inside(root, root / SNAPSHOT_RELATIVE)
        snapshot_bytes = _read_bounded_regular(
            target, MAX_SNAPSHOT_BYTES, "operational gap ledger snapshot"
        )
        if not snapshot_bytes:
            raise ValueError("operational gap ledger snapshot is missing or unbounded")
        value = json.loads(snapshot_bytes)
        if not isinstance(value, dict) or value.get("schema_version") != SNAPSHOT_SCHEMA:
            raise ValueError("operational gap ledger snapshot schema is invalid")
        claimed = str(value.get("projection_sha256") or "")
        body = {key: item for key, item in value.items() if key != "projection_sha256"}
        if not SHA256_PATTERN.fullmatch(claimed) or _digest(body) != claimed:
            raise ValueError("operational gap ledger snapshot hash is invalid")
        if (
            len(snapshot_bytes) != head.get("snapshot_size_bytes")
            or hashlib.sha256(snapshot_bytes).hexdigest() != head.get("snapshot_sha256")
        ):
            raise ValueError("operational gap ledger snapshot does not match its checkpoint")
        if (
            value.get("event_count") != head.get("event_count")
            or value.get("head_event_sha256") != head.get("head_event_sha256")
            or value.get("ledger_id") != head.get("ledger_id")
            or value.get("ledger_size_bytes") != head["ledger_fingerprint"]["size_bytes"]
        ):
            raise ValueError("operational gap ledger snapshot state is stale")
        snapshot = value
    if _read_bounded_regular(
        head_path, MAX_HEAD_BYTES, "operational gap ledger compact head"
    ) != head_a_bytes:
        raise ValueError("operational gap ledger checkpoint changed during read")
    return snapshot, head


def _read_checkpoint(
    root: Path, *, include_snapshot: bool, attempts: int = 3
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return _read_checkpoint_once(root, include_snapshot=include_snapshot)
        except (OSError, ValueError, json.JSONDecodeError) as candidate:
            error = candidate
            if attempt + 1 < max(1, attempts):
                time.sleep(0.005 * (attempt + 1))
    assert error is not None
    raise ValueError(f"operational gap ledger checkpoint is unavailable: {error}") from error


def read_head(root: Path) -> dict[str, Any]:
    """Return bounded dashboard metadata without acquiring the mutating lease."""

    root = root.resolve(strict=True)
    return _read_checkpoint(root, include_snapshot=False)[1]


def read_snapshot(root: Path) -> dict[str, Any]:
    """Return a hash-bound projection through a bounded optimistic read."""

    root = root.resolve(strict=True)
    snapshot, _head = _read_checkpoint(root, include_snapshot=True)
    assert snapshot is not None
    return snapshot


def guard_work_admission(
    snapshot: Mapping[str, Any], *, gap_id: str, effect: str,
    scope: Iterable[str], admission_event_id: str,
) -> dict[str, object]:
    """Fail closed unless an exact current work admission authorizes an effect.

    This is a governance check, not an execution authority transfer.  Codex or
    another host still performs the effect through its native security model.
    """

    checkpoints = snapshot.get("work_checkpoints", [])
    admissions = snapshot.get("work_admissions", [])
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ValueError("work guard requires an active checkpoint")
    if not isinstance(admissions, list):
        raise ValueError("work guard admission projection is invalid")
    active = checkpoints[-1]
    if str(active.get("active_gap_id") or "") != gap_id:
        raise ValueError("work guard gap does not match the active checkpoint")
    admission = next(
        (
            item for item in admissions
            if isinstance(item, Mapping)
            and item.get("event_id") == admission_event_id
        ),
        None,
    )
    if admission is None:
        raise ValueError("work guard admission event is absent")
    if (
        admission.get("checkpoint_event_id") != active.get("event_id")
        or admission.get("gap_id") != gap_id
    ):
        raise ValueError("work guard admission is not bound to the active checkpoint")
    if admission.get("effect") != effect:
        raise ValueError("work guard effect does not match the admission")

    def normalized(values: Iterable[str]) -> list[str]:
        result = [str(value).strip().replace("\\", "/") for value in values]
        if not result or any(not value for value in result) or len(result) != len(set(result)):
            raise ValueError("work guard scope must be a non-empty unique set")
        return sorted(result)

    requested_scope = normalized(scope)
    admitted_scope = admission.get("scope")
    if not isinstance(admitted_scope, list) or requested_scope != normalized(admitted_scope):
        raise ValueError("work guard scope does not exactly match the admission")
    return {
        "schema_version": "px.work-admission-guard/1.0",
        "valid": True,
        "gap_id": gap_id,
        "effect": effect,
        "scope": requested_scope,
        "checkpoint_event_id": active.get("event_id"),
        "admission_event_id": admission_event_id,
        "authority_boundary": (
            "PX governance validated; Codex host retains native execution, approval, and security authority."
        ),
    }


def _validate_transition_admission(card: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    after = str(payload.get("to_state") or "")
    if after == "implemented":
        _evidence(payload.get("implementation_evidence"), "implementation_evidence")
    elif after == "narrowly_verified":
        verification = payload.get("verification")
        if not isinstance(verification, Mapping):
            raise ValueError("narrowly_verified requires a verification object")
        tests_run = verification.get("tests_run")
        if not isinstance(tests_run, list) or not tests_run or any(not isinstance(item, str) or not item.strip() for item in tests_run):
            raise ValueError("narrowly_verified requires non-empty tests_run")
        _evidence(verification.get("results"), "verification.results")
    elif after == "integrated":
        _evidence(payload.get("integration_evidence"), "integration_evidence")
    elif after == "operationally_verified":
        unresolved = [
            stage for stage, item in card["interaction_chain"].items()
            if item["state"] not in {"present", "not_applicable"}
            or not item.get("evidence")
        ]
        if unresolved:
            raise ValueError(f"operationally_verified requires complete evidence-bound interaction stages: {unresolved}")
        _evidence(payload.get("operational_evidence"), "operational_evidence")
        if card.get("classification") in {
            "host-owned", "intentionally-unsupported", "out-of-scope"
        }:
            boundary = payload.get("boundary_evidence")
            if not isinstance(boundary, Mapping) or any(
                not str(boundary.get(field) or "").strip()
                for field in ("owner", "authority", "user_visible_behavior", "return_condition")
            ):
                raise ValueError("boundary classification requires exact ownership and user-visible behavior")
            _evidence(boundary.get("evidence"), "boundary_evidence.evidence")
    elif after == "superseded":
        replacement = str(payload.get("replacement_gap_id") or "")
        authority = str(payload.get("authority") or "")
        if not GAP_ID_PATTERN.fullmatch(replacement) or not authority.strip():
            raise ValueError("superseded requires replacement_gap_id and authority")
    elif after == "reopened":
        strengthening = payload.get("regression_strengthening")
        if not isinstance(strengthening, list) or not strengthening or any(not isinstance(item, str) or not item.strip() for item in strengthening):
            raise ValueError("reopened requires regression_strengthening")


def _validate_work_checkpoint_append(
    current: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    cards = current.get("cards", {})
    active_gap_id = str(payload.get("active_gap_id") or "")
    checkpoints = current.get("work_checkpoints", [])
    active_card = cards.get(active_gap_id)
    if active_card is None:
        raise ValueError("work checkpoint requires a known active card")
    if active_card.get("current_state") == "closed" and (
        not checkpoints
        or checkpoints[-1].get("active_gap_id") != active_gap_id
        or not str(payload.get("switching_to") or "")
    ):
        raise ValueError(
            "closed active card may only emit one explicit outgoing handoff"
        )
    if str(payload.get("next_action") or "") != str(cards[active_gap_id].get("next_action") or ""):
        raise ValueError("work checkpoint next_action must match the active card")
    unresolved = payload.get("unresolved_branch_gap_ids")
    newly = payload.get("newly_discovered_gap_ids")
    if (
        not isinstance(unresolved, list)
        or len(unresolved) != len(set(map(str, unresolved)))
        or not isinstance(newly, list)
        or len(newly) != len(set(map(str, newly)))
    ):
        raise ValueError("work checkpoint branch denominators must be unique arrays")
    if not checkpoints:
        if payload.get("previous_checkpoint_event_id") not in {None, ""}:
            raise ValueError("first work checkpoint cannot claim a predecessor")
        if newly:
            raise ValueError("first work checkpoint newly discovered denominator must be empty")
    else:
        previous = checkpoints[-1]
        if payload.get("previous_checkpoint_event_id") != previous.get("event_id"):
            raise ValueError("work checkpoint does not bind its exact predecessor")
        if (
            active_gap_id != previous.get("active_gap_id")
            and previous.get("switching_to") != active_gap_id
        ):
            raise ValueError("incoming work checkpoint does not match the outgoing switch target")
        previous_sequence = int(previous.get("sequence") or 0)
        expected_new = sorted(
            gap_id for gap_id, card in cards.items()
            if int(card.get("discovery_sequence") or 0) > previous_sequence
        )
        if sorted(map(str, newly)) != expected_new:
            raise ValueError("work checkpoint newly discovered denominator is incomplete")
        required_unresolved = {
            gap_id for gap_id in expected_new
            if gap_id != active_gap_id
            and cards[gap_id].get("current_state") not in {"closed", "superseded"}
        }
        if not required_unresolved.issubset(set(map(str, unresolved))):
            raise ValueError("work checkpoint omits a newly discovered unresolved branch")
    switching_to = str(payload.get("switching_to") or "")
    if switching_to and (
        switching_to == active_gap_id
        or switching_to not in cards
        or cards[switching_to].get("current_state") == "closed"
    ):
        raise ValueError("work checkpoint switching_to target is invalid")


def _parse_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"ledger contains a blank line at {line_number}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"ledger event {line_number} is not an object")
        events.append(value)
        if len(events) > MAX_EVENTS:
            raise ValueError("operational gap ledger exceeds its event bound")
    return events


def _write_recovery_receipt(
    root: Path, *, suffix: bytes, action: str, retained_bytes: int
) -> Path:
    directory = _inside(
        root, root / "evidence" / "operational-gap-ledger" / "recovery"
    )
    directory.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema_version": "px.operational-gap-ledger-recovery/1.0",
        "timestamp": _now(),
        "action": action,
        "ledger": LEDGER_RELATIVE.as_posix(),
        "retained_ledger_bytes": retained_bytes,
        "suffix_size_bytes": len(suffix),
        "suffix_sha256": hashlib.sha256(suffix).hexdigest(),
        "suffix_base64": base64.b64encode(suffix).decode("ascii"),
        "actor": "operational-gap-ledger-recovery",
        "process_id": os.getpid(),
    }
    receipt["receipt_sha256"] = _digest(receipt)
    target = directory / f"ledger-tail-{uuid4().hex}.json"
    encoded = _encoded_json(receipt)
    _write_bytes_atomically(target, encoded)
    return target


def _recover_torn_tail_unlocked(root: Path) -> Path | None:
    """Recover only a non-newline-terminated suffix, retaining exact bytes."""

    path = _inside(root, root / LEDGER_RELATIVE)
    if not path.exists() or path.stat().st_size == 0:
        return None
    data = _read_bounded_regular(
        path, MAX_LEDGER_BYTES, "operational gap ledger recovery source"
    )
    if data.endswith(b"\n"):
        return None
    boundary = data.rfind(b"\n") + 1
    prefix = data[:boundary]
    suffix = data[boundary:]
    if not suffix or len(suffix) > MAX_EVENT_BYTES:
        raise ValueError("operational ledger torn suffix is empty or exceeds its bound")
    prefix_events = _parse_jsonl_bytes(prefix)
    project_events(prefix_events)
    try:
        candidate = json.loads(suffix.decode("utf-8"))
        if not isinstance(candidate, dict):
            raise ValueError("final ledger value is not an event object")
        project_events([*prefix_events, candidate])
    except (UnicodeError, json.JSONDecodeError):
        receipt = _write_recovery_receipt(
            root,
            suffix=suffix,
            action="quarantined_torn_uncommitted_suffix",
            retained_bytes=boundary,
        )
        with path.open("r+b", buffering=0) as handle:
            handle.truncate(boundary)
            handle.flush()
            os.fsync(handle.fileno())
        return receipt
    except ValueError:
        # A syntactically complete event with invalid semantics is not proven
        # uncommitted. Preserve the authoritative bytes and fail closed.
        raise
    receipt = _write_recovery_receipt(
        root,
        suffix=suffix,
        action="completed_missing_record_delimiter",
        retained_bytes=len(data) + 1,
    )
    with path.open("ab", buffering=0) as handle:
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return receipt


def _append_bytes_unlocked(
    root: Path, data: bytes, *, expected_fingerprint: Mapping[str, int]
) -> None:
    path = _inside(root, root / LEDGER_RELATIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("operational gap ledger append target is not a physical file")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags, 0o600)
    try:
        before = os.fstat(descriptor)
        expected_size = int(expected_fingerprint["size_bytes"])
        identity_changed = expected_size > 0 and (
            int(before.st_dev) != int(expected_fingerprint["device"])
            or int(before.st_ino) != int(expected_fingerprint["inode"])
            or int(before.st_mtime_ns) != int(expected_fingerprint["mtime_ns"])
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != expected_size
            or identity_changed
        ):
            raise ValueError("operational gap ledger changed before append")
        position = 0
        while position < len(data):
            written = os.write(descriptor, data[position:])
            if written <= 0:
                raise OSError("operational gap ledger append made no progress")
            position += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if not existed and hasattr(os, "O_DIRECTORY"):
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _prepare_event(
    root: Path,
    current: Mapping[str, Any],
    *,
    event_type: str,
    payload: Mapping[str, Any],
    actor: str,
    timestamp: str | None,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    if event_type not in EVENT_TYPES:
        raise ValueError("unsupported operational ledger event type")
    _nonempty(actor, "actor")
    event_count = int(current.get("event_count") or 0)
    if not event_count and event_type != "ledger_initialized":
        raise ValueError("initialize the operational ledger first")
    if event_count and event_type == "ledger_initialized":
        raise ValueError("operational ledger is already initialized")
    if event_count >= MAX_EVENTS:
        raise ValueError("operational gap ledger event bound would be exceeded")
    event_timestamp = timestamp or _now()
    _iso_utc(event_timestamp, "event timestamp")
    prepared_payload = dict(payload)
    if event_type == "card_discovered":
        if str(prepared_payload.get("gap_id") or "") == "AUTO":
            prepared_payload["gap_id"] = f"PX-OS-{_maximum_gap_ordinal(current) + 1:03d}"
        discovered_at = prepared_payload.get("discovered_at")
        if discovered_at in {None, "", "AUTO"}:
            prepared_payload["discovered_at"] = event_timestamp
        elif _iso_utc(discovered_at, "discovered_at") != _iso_utc(
            event_timestamp, "event timestamp"
        ):
            raise ValueError("discovered_at must exactly match the authoritative event timestamp")
        discovered_by = prepared_payload.get("discovered_by")
        if discovered_by in {None, "", "AUTO"}:
            prepared_payload["discovered_by"] = actor
        elif str(discovered_by) != actor:
            raise ValueError("discovered_by must exactly match the authoritative event actor")
        prepared_payload.setdefault(
            "discovery_evidence",
            [{
                "reference": prepared_payload.get("discovery_source", ""),
                "claim": prepared_payload.get("observed_behavior", ""),
            }],
        )
        prepared_payload = dict(_bind_evidence(root, prepared_payload))
        discovery_source = str(prepared_payload.get("discovery_source") or "").strip()
        discovery_source_path = (
            _resolved_evidence_path(root, discovery_source)
            if discovery_source
            else None
        )
        if any(
            not isinstance(ref, Mapping)
            or not isinstance(ref.get("path"), str)
            or not ref.get("path").strip()
            or not isinstance(ref.get("symbols"), list)
            or any(
                not isinstance(symbol, str) or not symbol.strip()
                for symbol in ref["symbols"]
            )
            or (
                not ref["symbols"]
                and (
                    discovery_source_path is None
                    or _resolved_evidence_path(root, str(ref.get("path") or "")) != discovery_source_path
                )
            )
            for ref in prepared_payload.get("source_refs", [])
        ):
            raise ValueError("new source_refs require path and symbols metadata")
        _validate_chain(prepared_payload.get("interaction_chain"), require_evidence=True)
        _validate_card(
            prepared_payload, allow_local_discovery_empty_symbols=True
        )
    else:
        prepared_payload = dict(_bind_evidence(root, prepared_payload))
    if event_type == "card_transition":
        cards = current.get("cards", {})
        gap_id = str(prepared_payload.get("gap_id") or "")
        if gap_id not in cards:
            raise ValueError(f"invalid card transition {gap_id}: unknown card")
        card = cards[gap_id]
        before = str(prepared_payload.get("from_state") or "")
        after = str(prepared_payload.get("to_state") or "")
        if before != card.get("current_state") or not _transition_allowed(before, after):
            raise ValueError(f"invalid card transition {gap_id}: {before} -> {after}")
    if event_type in {"control_disposition", "control_disposition_revised"}:
        disposition = str(
            prepared_payload.get(
                "disposition", prepared_payload.get("to_disposition", "")
            )
        )
        observation = prepared_payload.get("observation")
        if disposition == "operational" and observation is None:
            raise ValueError(
                "operational control disposition requires a typed current-host observation"
            )
        if observation is not None:
            prepared_payload["observation"] = _validate_control_observation(
                observation, disposition=disposition
            )
    if event_type == "report_registered":
        prepared_payload.update(_validate_report_manifest(root, prepared_payload))
    if event_type == "surface_inventory_revised" and "retired_controls" not in prepared_payload:
        raise ValueError("new surface inventory revisions require an exact retired_controls array")
    if event_type == "work_checkpoint":
        _validate_work_checkpoint_append(current, prepared_payload)
    if event_type == "card_transition" and prepared_payload.get("to_state") == "reopened":
        gap_id = str(prepared_payload.get("gap_id") or "")
        card = current.get("cards", {}).get(gap_id, {})
        target = str(prepared_payload.get("contradicted_transition_event_sha256") or "")
        valid_targets = {
            str(row.get("event_sha256") or "")
            for row in card.get("history", [])
            if row.get("event") == "transition"
            and row.get("to") in {"narrowly_verified", "operationally_verified", "closed"}
        }
        if not SHA256_PATTERN.fullmatch(target) or target not in valid_targets:
            raise ValueError("reopen must bind an exact prior verification or closure event")
    if event_type == "card_transition" and prepared_payload.get("to_state") == "closed":
        closure = _evidence(prepared_payload.get("closure_evidence"), "closure_evidence")
        if any(
            "artifact_sha256" not in item
            and not str(item.get("reference") or "").startswith("sha256:")
            and "#sha256=" not in str(item.get("reference") or "")
            for item in closure
        ):
            raise ValueError("closure_evidence must be bound to immutable artifact bytes")
        prepared_payload["closure_evidence"] = closure
    if event_type == "card_discovered":
        identity = (
            prepared_payload.get("parent_surface"), prepared_payload.get("feature"),
            prepared_payload.get("control_action"),
        )
        terminal_matches = [
            gap_id for gap_id, existing in current.get("cards", {}).items()
            if (existing.get("parent_surface"), existing.get("feature"), existing.get("control_action")) == identity
            and existing.get("current_state") in {"operationally_verified", "closed"}
        ]
        if terminal_matches and prepared_payload.get("duplicate_of_gap_id") not in terminal_matches:
            raise ValueError("new card duplicates a terminal card without explicit duplicate_of_gap_id")
    if event_type == "card_annotated":
        patch = prepared_payload.get("patch", {})
        if isinstance(patch, Mapping) and "interaction_chain" in patch:
            _validate_chain(patch["interaction_chain"], require_evidence=True)
        if isinstance(patch, Mapping) and "source_refs" in patch and any(
            not isinstance(ref, Mapping)
            or not isinstance(ref.get("symbols"), list)
            or any(not isinstance(symbol, str) or not symbol.strip() for symbol in ref["symbols"])
            for ref in patch["source_refs"]
        ):
            raise ValueError("new source_refs require non-empty relevant symbols")
    sequence = event_count + 1
    ledger_id = (
        str(prepared_payload.get("ledger_id") or "uninitialized")
        if event_type == "ledger_initialized"
        else str(current.get("ledger_id") or "")
    )
    event = {
        "schema_version": SCHEMA,
        "sequence": sequence,
        "event_id": f"gap-event:{ledger_id}:{sequence:012d}",
        "event_type": event_type,
        "timestamp": event_timestamp,
        "actor": actor,
        "previous_event_sha256": current.get("head_event_sha256"),
        "payload": json.loads(_canonical(prepared_payload)),
    }
    event["event_sha256"] = _digest(event)
    encoded = json.dumps(
        event, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError("operational gap ledger event byte bound would be exceeded")
    next_snapshot = project_events([event], base_snapshot=current)
    return event, next_snapshot, encoded


def _load_append_base_unlocked(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        snapshot, head = _read_checkpoint_once(root, include_snapshot=True)
        assert snapshot is not None
        return snapshot, head
    except (OSError, ValueError, json.JSONDecodeError):
        _recover_torn_tail_unlocked(root)
        events = _read_events_unlocked(root)
        return project_events(events), None


def _verification_basis(
    snapshot: Mapping[str, Any], predecessor: Mapping[str, Any] | None
) -> dict[str, Any]:
    if predecessor is None:
        return {
            "kind": "full_replay",
            "verified_event_count": snapshot.get("event_count"),
            "verified_head_event_sha256": snapshot.get("head_event_sha256"),
        }
    prior_basis = predecessor.get("verification_basis", {})
    return {
        "kind": "incremental_from_verified_checkpoint",
        "full_replay_anchor_event_count": prior_basis.get(
            "full_replay_anchor_event_count",
            prior_basis.get("verified_event_count"),
        ),
        "full_replay_anchor_event_sha256": prior_basis.get(
            "full_replay_anchor_event_sha256",
            prior_basis.get("verified_head_event_sha256"),
        ),
    }


def append_events(
    root: Path, entries: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Append a bounded event batch under one lease and one checkpoint load."""

    root = root.resolve(strict=True)
    requested = list(islice(iter(entries), MAX_BATCH_EVENTS + 1))
    if not requested or len(requested) > MAX_BATCH_EVENTS:
        raise ValueError("operational ledger batch must contain 1..MAX_BATCH_EVENTS entries")
    if any(not isinstance(item, Mapping) for item in requested):
        raise ValueError("operational ledger batch entries must be objects")
    lock = _inside(root, root / LOCK_RELATIVE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock, timeout_seconds=30.0):
        current, predecessor = _load_append_base_unlocked(root)
        starting_fingerprint = _ledger_fingerprint(root)
        events: list[dict[str, Any]] = []
        encoded_events: list[bytes] = []
        for item in requested:
            event, current, encoded = _prepare_event(
                root,
                current,
                event_type=str(item.get("event_type") or ""),
                payload=item.get("payload", {}),
                actor=str(item.get("actor") or ""),
                timestamp=item.get("timestamp"),
            )
            events.append(event)
            encoded_events.append(encoded)
        appended = b"".join(encoded_events)
        predicted_size = starting_fingerprint["size_bytes"] + len(appended)
        if predicted_size > MAX_LEDGER_BYTES:
            raise ValueError("operational gap ledger byte bound would be exceeded")
        sealed, snapshot_bytes = _seal_snapshot(
            current, ledger_size_bytes=predicted_size
        )
        basis = _verification_basis(sealed, predecessor)
        previous_checkpoint = (
            str(predecessor.get("checkpoint_sha256")) if predecessor else None
        )
        # Bound the compact publication before the authoritative append. The
        # actual filesystem identity has no larger representation than these
        # conservative integer placeholders.
        _build_head(
            sealed,
            snapshot_bytes,
            fingerprint={
                "device": 2**63 - 1,
                "inode": 2**63 - 1,
                "size_bytes": predicted_size,
                "mtime_ns": 2**63 - 1,
            },
            tail_event=events[-1],
            verification_basis=basis,
            previous_checkpoint_sha256=previous_checkpoint,
        )
        _append_bytes_unlocked(
            root, appended, expected_fingerprint=starting_fingerprint
        )
        actual_fingerprint = _ledger_fingerprint(root)
        if actual_fingerprint["size_bytes"] != predicted_size:
            raise OSError("operational gap ledger append size is inconsistent")
        published = _write_snapshot_unlocked(root, current, predicted_size)
        published_bytes = _encoded_json(published)
        _head, head_bytes = _build_head(
            published,
            published_bytes,
            fingerprint=actual_fingerprint,
            tail_event=events[-1],
            verification_basis=basis,
            previous_checkpoint_sha256=previous_checkpoint,
        )
        _write_bytes_atomically(_inside(root, root / HEAD_RELATIVE), head_bytes)
        return events


def append_event(
    root: Path,
    event_type: str,
    payload: Mapping[str, Any],
    *,
    actor: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return append_events(
        root,
        [{
            "event_type": event_type,
            "payload": dict(payload),
            "actor": actor,
            "timestamp": timestamp,
        }],
    )[0]


def append_transition_admission_backfill(
    root: Path,
    payload: Mapping[str, Any],
    *,
    actor: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Append a historical admission repair only after authoritative full replay.

    This deliberately bypasses the warm-delta path: a backfill may explain an
    earlier transition that the strengthened reducer now rejects, so both its
    exact historical target and the resulting projection must be proven while
    the mutating lease is held.
    """

    root = root.resolve(strict=True)
    _nonempty(actor, "actor")
    lock = _inside(root, root / LOCK_RELATIVE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock, timeout_seconds=30.0):
        _recover_torn_tail_unlocked(root)
        events = _read_events_unlocked(root)
        if not events or len(events) >= MAX_EVENTS:
            raise ValueError("transition admission backfill requires an initialized bounded ledger")
        starting_fingerprint = _ledger_fingerprint(root)
        tail = events[-1]
        first_payload = events[0].get("payload", {})
        ledger_id = str(first_payload.get("ledger_id") or "") if isinstance(first_payload, Mapping) else ""
        _nonempty(ledger_id, "ledger_id")
        prepared_payload = dict(_bind_evidence(root, payload))
        sequence = len(events) + 1
        event: dict[str, Any] = {
            "schema_version": SCHEMA,
            "sequence": sequence,
            "event_id": f"gap-event:{ledger_id}:{sequence:012d}",
            "event_type": "transition_admission_backfilled",
            "timestamp": timestamp or _now(),
            "actor": actor,
            "previous_event_sha256": tail.get("event_sha256"),
            "payload": json.loads(_canonical(prepared_payload)),
        }
        event["event_sha256"] = _digest(event)
        encoded = json.dumps(
            event, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError("operational gap ledger event byte bound would be exceeded")
        snapshot = project_events([*events, event])
        predicted_size = starting_fingerprint["size_bytes"] + len(encoded)
        if predicted_size > MAX_LEDGER_BYTES:
            raise ValueError("operational gap ledger byte bound would be exceeded")
        sealed, snapshot_bytes = _seal_snapshot(snapshot, ledger_size_bytes=predicted_size)
        predecessor: dict[str, Any] | None = None
        try:
            _unused, predecessor = _read_checkpoint_once(root, include_snapshot=False)
        except (OSError, ValueError, json.JSONDecodeError):
            predecessor = None
        basis = _verification_basis(sealed, None)
        previous_checkpoint = (
            str(predecessor.get("checkpoint_sha256")) if predecessor else None
        )
        _build_head(
            sealed,
            snapshot_bytes,
            fingerprint={
                "device": 2**63 - 1,
                "inode": 2**63 - 1,
                "size_bytes": predicted_size,
                "mtime_ns": 2**63 - 1,
            },
            tail_event=event,
            verification_basis=basis,
            previous_checkpoint_sha256=previous_checkpoint,
        )
        _append_bytes_unlocked(root, encoded, expected_fingerprint=starting_fingerprint)
        fingerprint = _ledger_fingerprint(root)
        if fingerprint["size_bytes"] != predicted_size:
            raise OSError("operational gap ledger append size is inconsistent")
        published = _write_snapshot_unlocked(root, snapshot, predicted_size)
        published_bytes = _encoded_json(published)
        _head, head_bytes = _build_head(
            published,
            published_bytes,
            fingerprint=fingerprint,
            tail_event=event,
            verification_basis=basis,
            previous_checkpoint_sha256=previous_checkpoint,
        )
        _write_bytes_atomically(_inside(root, root / HEAD_RELATIVE), head_bytes)
        return event


def write_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    lock = _inside(root, root / LOCK_RELATIVE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock, timeout_seconds=30.0):
        _recover_torn_tail_unlocked(root)
        events = _read_events_unlocked(root)
        snapshot = project_events(events)
        fingerprint = _ledger_fingerprint(root)
        sealed, snapshot_bytes = _seal_snapshot(
            snapshot, ledger_size_bytes=fingerprint["size_bytes"]
        )
        basis = _verification_basis(sealed, None)
        _build_head(
            sealed,
            snapshot_bytes,
            fingerprint=fingerprint,
            tail_event=events[-1] if events else None,
            verification_basis=basis,
            previous_checkpoint_sha256=None,
        )
        published = _write_snapshot_unlocked(root, snapshot, fingerprint["size_bytes"])
        published_bytes = _encoded_json(published)
        _head, head_bytes = _build_head(
            published,
            published_bytes,
            fingerprint=fingerprint,
            tail_event=events[-1] if events else None,
            verification_basis=basis,
            previous_checkpoint_sha256=None,
        )
        _write_bytes_atomically(_inside(root, root / HEAD_RELATIVE), head_bytes)
        return published
