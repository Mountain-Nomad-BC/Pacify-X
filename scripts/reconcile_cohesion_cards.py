"""Validate and reconcile the finite cohesion punch-card denominator.

The command is check-only by default.  ``--apply`` is required to change the
card projection.  The first supported target is ``downstream_green``.  Closing
the source/proof cards additionally requires a successful successor-candidate
installed-operational summary.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from runtime.wal_transaction import (  # noqa: E402
    JsonTextArtifact,
    JsonTransition,
    JsonWal,
    TextArtifact,
)

CARD_DIRECTORY = Path(
    ".engineering-bootstrap/punch-cards/cohesion-closure-20260904"
)
AUDIT_CARD_IDS = {
    "PX-COMM-001",
    "PX-COMM-002",
    "PX-COMM-003",
    "PX-COMM-004",
    "PX-COMM-005",
    "PX-COMM-006",
}
SOURCE_CARD_IDS = {
    "PX-ASSURE-001",
    "PX-ASSURE-002",
    "PX-ASSURE-003",
    "PX-CORE-001",
    "PX-CORE-002",
    "PX-CORE-003",
    "PX-CORE-004",
    "PX-ROUTE-001",
    "PX-ROUTE-002",
    "PX-ROUTE-003",
    "PX-ROUTE-004",
    "PX-ROUTE-005",
    "PX-MODEL-001",
    "PX-MODEL-002",
    "PX-MODEL-003",
    "PX-AGENT-001",
    "PX-MEM-001",
    "PX-AGENT-002",
    "PX-AGENT-003",
    "PX-PROVIDER-001",
    "PX-FOUNDRY-001",
    "PX-FOUNDRY-002",
    "PX-SKILL-001",
    "PX-SKILL-002",
    "PX-SKILL-003",
    "PX-GRAPH-001",
    "PX-EFF-001",
    "PX-EFF-002",
    "PX-EFF-003",
    "PX-SYS-001",
    "PX-SYS-002",
    "PX-SYS-003",
    "PX-REPAIR-001",
    "PX-AUTH-001",
    "PX-AUTH-002",
    "PX-LEDGER-001",
    "PX-LEDGER-002",
}
ALL_CARD_IDS = AUDIT_CARD_IDS | SOURCE_CARD_IDS
CARD_FIELDS = {
    "card_id",
    "title",
    "severity",
    "type",
    "status",
    "root_cause",
    "source_requirement",
    "live_evidence",
    "files",
    "symbols",
    "dependencies",
    "downstream_consumers",
    "change_classes",
    "implementation_steps",
    "negative_cases",
    "focused_tests",
    "affected_tests",
    "affected_sections",
    "projection_invalidations",
    "evidence_required",
    "rollback",
    "acceptance_criteria",
    "completion_evidence",
}
LIFECYCLE = (
    "planned",
    "admitted",
    "in_progress",
    "focused_green",
    "downstream_green",
    "closed",
)
DEFAULT_EVIDENCE = (
    Path("evidence/commencement-repair/repair-freeze-20260905.json"),
    Path("evidence/release/final99-full-profile-pass-20260905.json"),
    Path("evidence/release/final99-validation-pass-20260905.json"),
    Path(
        "evidence/release/"
        "final99-route-projection-settlement-complete-focused-repair-20260905.json"
    ),
)
EXTERNAL_ORCHESTRATION = Path(
    "C:/Users/Ben/Downloads/px looks/PX_COMMENCEMENT_ORCHESTRATION_2026-09-04.md"
)
KNOWN_AFFECTED_SECTIONS = {
    "dashboard-extension",
    "structural-adversarial",
    "testing-governance",
}
RELEASE_STAGES = (
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "certify",
)
PRIOR_AUTOMATION_STEPS = (
    "archive_clear",
    "reconcile",
    "identity",
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
)
RECOVERY_JOURNAL = Path(
    ".engineering-bootstrap/wal/cohesion-card-reconciliation"
)


class ReconciliationError(ValueError):
    """The card denominator or its evidence is not safe to reconcile."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReconciliationError(f"unreadable JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReconciliationError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_record(path: Path, *, display: str, **extra: object) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ReconciliationError(f"evidence is not a regular retained file: {display}")
    return {
        "path": display,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        **extra,
    }


def _inside(root: Path, relative: Path) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ReconciliationError(f"path escapes project root: {relative}") from error
    return target


def _nonempty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _parse_checksums(directory: Path) -> dict[str, str]:
    path = directory / "SHA256SUMS"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReconciliationError(f"unreadable checksum manifest: {error}") from error
    records: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\\/]+)", line)
        if not match or match.group(2) in records:
            raise ReconciliationError(f"invalid checksum manifest line: {line!r}")
        records[match.group(2)] = match.group(1)
    expected = {"dag.json", "README.md", *(f"{card_id}.json" for card_id in ALL_CARD_IDS)}
    if set(records) != expected:
        raise ReconciliationError(
            "checksum inventory mismatch: "
            f"missing={sorted(expected - set(records))}, "
            f"extra={sorted(set(records) - expected)}"
        )
    mismatched = [
        name for name, expected_sha in records.items()
        if _sha256(directory / name) != expected_sha
    ]
    if mismatched:
        raise ReconciliationError(f"checksum mismatch: {sorted(mismatched)}")
    return records


def _validate_card(card_id: str, card: Mapping[str, object]) -> None:
    missing = sorted(CARD_FIELDS - set(card))
    if missing:
        raise ReconciliationError(f"{card_id}: missing fields: {missing}")
    if card.get("card_id") != card_id:
        raise ReconciliationError(f"{card_id}: card_id does not match its path")
    if card.get("status") not in LIFECYCLE:
        raise ReconciliationError(f"{card_id}: invalid status: {card.get('status')!r}")
    for field in (
        "title",
        "severity",
        "type",
        "root_cause",
        "source_requirement",
        "rollback",
    ):
        if not isinstance(card.get(field), str) or not str(card[field]).strip():
            raise ReconciliationError(f"{card_id}: {field} must be a non-empty string")
    evidence_fields = (
        "live_evidence",
        "files",
        "symbols",
        "change_classes",
        "implementation_steps",
        "negative_cases",
        "focused_tests",
        "affected_tests",
        "affected_sections",
        "projection_invalidations",
        "evidence_required",
        "acceptance_criteria",
    )
    for field in evidence_fields:
        value = card.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and bool(item.strip()) for item in value
        ):
            raise ReconciliationError(f"{card_id}: {field} must be a string list")
        if card_id in SOURCE_CARD_IDS and not _nonempty_strings(value):
            raise ReconciliationError(f"{card_id}: {field} must contain evidence-bearing strings")
    for field in ("dependencies", "downstream_consumers", "completion_evidence"):
        value = card.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and bool(item.strip()) for item in value
        ):
            raise ReconciliationError(f"{card_id}: {field} must be a string list")


def _validate_dag(
    dag: Mapping[str, object], cards: Mapping[str, Mapping[str, object]]
) -> None:
    if dag.get("card_count") != 43 or dag.get("edge_count") != 86:
        raise ReconciliationError("DAG must retain the frozen 43-card/86-edge denominator")
    nodes = dag.get("nodes")
    if not isinstance(nodes, list):
        raise ReconciliationError("DAG nodes must be a list")
    node_map = {
        str(node.get("card_id")): node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("card_id"), str)
    }
    if set(node_map) != ALL_CARD_IDS or len(node_map) != len(nodes):
        raise ReconciliationError("DAG node inventory is not the exact 43-card denominator")
    edge_count = 0
    for card_id, card in cards.items():
        node = node_map[card_id]
        if node.get("path") != f"{card_id}.json":
            raise ReconciliationError(f"{card_id}: DAG path mismatch")
        dependencies = set(map(str, card.get("dependencies", ())))
        consumers = set(map(str, card.get("downstream_consumers", ())))
        if dependencies != set(map(str, node.get("dependencies", ()))):
            raise ReconciliationError(f"{card_id}: dependency mismatch between card and DAG")
        if consumers != set(map(str, node.get("downstream_consumers", ()))):
            raise ReconciliationError(f"{card_id}: consumer mismatch between card and DAG")
        if not dependencies <= ALL_CARD_IDS or not consumers <= ALL_CARD_IDS:
            raise ReconciliationError(f"{card_id}: dependency references an unknown card")
        edge_count += len(dependencies)
        for dependency in dependencies:
            if card_id not in cards[dependency].get("downstream_consumers", ()):
                raise ReconciliationError(
                    f"{dependency} -> {card_id}: reverse consumer edge is absent"
                )
    if edge_count != 86:
        raise ReconciliationError(f"DAG dependency edge count changed: {edge_count}")
    topological = dag.get("topological_order")
    if not isinstance(topological, list) or set(map(str, topological)) != ALL_CARD_IDS:
        raise ReconciliationError("DAG topological order is not the exact card inventory")
    positions = {str(card_id): index for index, card_id in enumerate(topological)}
    for card_id, card in cards.items():
        for dependency in map(str, card.get("dependencies", ())):
            if positions[dependency] >= positions[card_id]:
                raise ReconciliationError(f"DAG is not topological at {dependency} -> {card_id}")


def _validate_evidence(
    root: Path, evidence: Iterable[Path], *, require_final99_identity: bool
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relative in evidence:
        path = _inside(root, relative)
        if not path.is_file():
            raise ReconciliationError(f"required evidence is absent: {relative.as_posix()}")
        payload = _load_json(path)
        records.append(
            _hash_record(
                path,
                display=relative.as_posix(),
                schema_version=payload.get("schema_version"),
            )
        )
    by_path = {record["path"]: _load_json(root / str(record["path"])) for record in records}
    freeze = by_path[DEFAULT_EVIDENCE[0].as_posix()]
    if (
        freeze.get("schema_version") != "px.repair-freeze/1.0"
        or freeze.get("campaign_id") != "pacify-x-cohesion-closure-repair-20260905"
        or freeze.get("phase") != "repair_frozen"
        or freeze.get("intake_open") is not False
        or freeze.get("unresolved") != []
        or freeze.get("certification_claim") is not False
    ):
        raise ReconciliationError("commencement repair freeze is not closed")
    source = freeze.get("source_classification")
    if (
        not isinstance(source, dict)
        or source.get("valid") is not True
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(source.get(field) or ""))
            for field in ("product_digest", "harness_digest")
        )
    ):
        raise ReconciliationError("commencement repair freeze lacks source identity")
    _require_zero_resources(freeze.get("resource_state"), label="repair freeze")
    benchmark_relative = freeze.get("ledger_benchmark")
    if not isinstance(benchmark_relative, str):
        raise ReconciliationError("repair freeze lacks its ledger benchmark")
    benchmark = _load_json(_inside(root, Path(benchmark_relative)))
    if (
        benchmark.get("schema_version")
        != "px.operational-gap-ledger-benchmark/1.0"
        or benchmark.get("valid") is not True
        or benchmark.get("custody_guarantees_changed") is not False
        or not isinstance(benchmark.get("budget_results"), dict)
        or not all(benchmark["budget_results"].values())
    ):
        raise ReconciliationError("repair freeze ledger benchmark is not passing")
    full = by_path[DEFAULT_EVIDENCE[1].as_posix()]
    final99 = "pacify-x-certification-20260905-final99-single"
    identity_sha = full.get("release_identity_sha256")
    if (
        full.get("schema_version") != "px.full-profile-receipt/1.0"
        or full.get("campaign_id") != final99
        or not re.fullmatch(r"[0-9a-f]{64}", str(identity_sha or ""))
        or full.get("owner_invocations") != 1
        or full.get("passed_group_count") != full.get("required_group_count")
        or full.get("failed_groups") != []
        or full.get("timed_out") is not False
        or full.get("process_tree_terminated") is not True
        or full.get("group_refresh_workspace_reclaimed") is not True
        or full.get("cross_group_workspace_reclaimed") is not True
        or full.get("stage_status") != "passed"
        or full.get("valid") is not True
    ):
        raise ReconciliationError("final99 full-profile evidence is not passing")
    _require_zero_resources(full, label="final99 full profile")
    _validate_path_hash_fields(
        root, full, path_field="full_log", hash_field="full_log_sha256", label="final99 full log"
    )
    validation = by_path[DEFAULT_EVIDENCE[2].as_posix()]
    if (
        validation.get("schema_version") != "px.validation-receipt/1.0"
        or validation.get("campaign_id") != final99
        or validation.get("release_identity_sha256") != identity_sha
        or validation.get("owner_invocations") != 1
        or validation.get("errors") != []
        or validation.get("certification_claim") is not False
        or validation.get("stage_status") != "passed"
        or validation.get("valid") is not True
    ):
        raise ReconciliationError("final99 validation evidence is not passing")
    _require_zero_resources(validation, label="final99 validation")
    _validate_path_hash_fields(
        root,
        validation,
        path_field="validation_log",
        hash_field="validation_log_sha256",
        label="final99 validation log",
    )
    if require_final99_identity:
        release_identity = _load_json(
            root / ".engineering-bootstrap/processing-order/release-identity.json"
        )
        kernel = release_identity.get("identity")
        stages = release_identity.get("stages")
        if (
            release_identity.get("schema_version") != "px.release-campaign/1.0"
            or release_identity.get("campaign_id") != final99
            or release_identity.get("repair_campaign_id")
            != "pacify-x-cohesion-closure-repair11-20260905"
            or release_identity.get("state") != "failed"
            or release_identity.get("apply_count") != 1
            or release_identity.get("active_claim") is not None
            or not isinstance(kernel, dict)
            or kernel.get("schema_version") != "px.release-identity-kernel/2.0"
            or kernel.get("campaign_id") != final99
            or kernel.get("repair_campaign_id")
            != release_identity.get("repair_campaign_id")
            or kernel.get("release_identity_sha256") != identity_sha
            or kernel.get("release_identity_sha256")
            != _object_sha256(
                {
                    key: value
                    for key, value in kernel.items()
                    if key != "release_identity_sha256"
                }
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(kernel.get("source_product_digest") or "")
            )
            or kernel.get("source_harness_digest") != source.get("harness_digest")
            or not isinstance(stages, dict)
            or stages.get("installed_operational", {}).get("status") != "failed"
            or stages.get("certify") != {"status": "pending", "claim_id": None}
        ):
            raise ReconciliationError("current final99 release identity is not exact")
    repair = by_path[DEFAULT_EVIDENCE[3].as_posix()]
    if (
        repair.get("schema_version") != "px.focused-repair-evidence/1.0"
        or repair.get("campaign_id")
        != "pacify-x-cohesion-closure-repair12-20260905"
        or repair.get("predecessor_release_campaign_id") != final99
        or repair.get("status") != "focused_green"
        or repair.get("final99_replayed") is not False
        or repair.get("certification_claim") is not False
    ):
        raise ReconciliationError("repair12 evidence is not focused-green and non-certifying")
    tests = repair.get("tests")
    if not isinstance(tests, list) or len(tests) != 3:
        raise ReconciliationError("repair12 focused test denominator is not exact")
    for index, row in enumerate(tests):
        if not isinstance(row, dict):
            raise ReconciliationError("repair12 focused test record is malformed")
        _validate_path_hash_fields(
            root,
            row,
            path_field="reference",
            hash_field="artifact_sha256",
            size_field="artifact_size",
            label=f"repair12 test {index}",
        )
    installed = repair.get("installed_focused_proofs")
    expected_profiles = {"studio-lifecycle", "coordination-memory", "native-dialog-boundary"}
    if (
        not isinstance(installed, list)
        or len(installed) != 3
        or {row.get("profile") for row in installed if isinstance(row, dict)}
        != expected_profiles
    ):
        raise ReconciliationError("repair12 installed proof denominator is not exact")
    for row in installed:
        if (
            not isinstance(row, dict)
            or row.get("terminal_state") != "completed"
            or row.get("issues") != 0
            or row.get("host_errors") != 0
            or row.get("cleanup_reclaimed") is not True
        ):
            raise ReconciliationError("repair12 installed proof is not complete")
        for stem in ("receipt", "report"):
            _validate_path_hash_fields(
                root,
                row,
                path_field=stem,
                hash_field=f"{stem}_sha256",
                label=f"repair12 {row['profile']} {stem}",
            )
    immutable = repair.get("immutable_artifact")
    if not isinstance(immutable, dict) or immutable.get("unchanged") is not True:
        raise ReconciliationError("repair12 immutable artifact is not retained")
    _validate_path_hash_fields(
        root,
        immutable,
        path_field="reference",
        hash_field="artifact_sha256",
        size_field="artifact_size",
        label="repair12 immutable artifact",
    )
    return records


def _require_zero_resources(value: object, *, label: str) -> None:
    if not isinstance(value, dict) or any(
        value.get(field) != 0
        for field in ("resource_count", "active_processes", "cleanup_failures")
    ):
        raise ReconciliationError(f"{label} does not have a zero resource denominator")


def _validate_path_hash_fields(
    root: Path,
    value: Mapping[str, object],
    *,
    path_field: str,
    hash_field: str,
    label: str,
    size_field: str | None = None,
) -> dict[str, object]:
    raw_path = value.get(path_field)
    expected_sha = value.get(hash_field)
    if not isinstance(raw_path, str) or not raw_path:
        raise ReconciliationError(f"{label} path is absent")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ReconciliationError(f"{label} hash is absent")
    path = _inside(root, Path(raw_path))
    record = _hash_record(path, display=Path(raw_path).as_posix())
    if record["sha256"] != expected_sha:
        raise ReconciliationError(f"{label} bytes do not match the retained hash")
    if size_field is not None and value.get(size_field) != record["size"]:
        raise ReconciliationError(f"{label} size does not match the retained bytes")
    return record


def _validate_card_evidence(
    root: Path, card_id: str, card: Mapping[str, object]
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for reference in map(str, card["live_evidence"]):
        raw_base, separator, anchor = reference.partition("#")
        raw_path = Path(raw_base)
        if raw_path.is_absolute():
            path = raw_path.resolve()
            if path != EXTERNAL_ORCHESTRATION.resolve():
                raise ReconciliationError(
                    f"{card_id}: external live evidence is not allowlisted: {raw_base}"
                )
        else:
            path = _inside(root, raw_path)
        record = _hash_record(
            path,
            display=raw_path.as_posix(),
            anchor=anchor if separator else None,
            evidence_kind="card_live_evidence",
        )
        if path == EXTERNAL_ORCHESTRATION.resolve():
            if anchor != card_id or card_id not in path.read_text(encoding="utf-8"):
                raise ReconciliationError(
                    f"{card_id}: external orchestration anchor is absent"
                )
        else:
            payload = _load_json(path)
            relative = path.relative_to(root).as_posix()
            if relative.endswith("/finding-dispositions.json"):
                if (
                    payload.get("schema_version") != "px.forensic-live-dispositions/1.0"
                    or not re.fullmatch(r"PX-AUD-\d{3}", anchor)
                ):
                    raise ReconciliationError(f"{card_id}: forensic evidence is malformed")
                findings = payload.get("findings")
                if not isinstance(findings, list) or not any(
                    isinstance(item, dict)
                    and item.get("id") == anchor
                    and item.get("disposition") == "PRESENT_LIVE"
                    and item.get("repair_required") is True
                    for item in findings
                ):
                    raise ReconciliationError(
                        f"{card_id}: forensic evidence anchor is not a live finding"
                    )
            elif relative.endswith("/current-owners-and-gaps.json"):
                areas = payload.get("areas")
                if (
                    separator
                    or payload.get("schema_version")
                    != "px.commencement-current-owners-and-gaps/1.0"
                    or not isinstance(areas, list)
                    or not any(
                        isinstance(area, dict) and card_id in area.get("cards", ())
                        for area in areas
                    )
                ):
                    raise ReconciliationError(
                        f"{card_id}: current-owner evidence does not own the card"
                    )
            elif relative.endswith("/live-state.json"):
                if (
                    separator
                    or card_id != "PX-REPAIR-001"
                    or payload.get("schema_version") != "px.commencement-live-state/1.0"
                    or payload.get("source_classification", {}).get("valid") is not True
                    or payload.get("generated_artifacts", {}).get("valid") is not True
                ):
                    raise ReconciliationError(f"{card_id}: live-state evidence is malformed")
            else:
                raise ReconciliationError(
                    f"{card_id}: live evidence base is not recognized: {relative}"
                )
        records.append(record)

    declared_records: list[dict[str, object]] = []
    for declared in map(str, card["files"]):
        relative = Path(declared)
        if relative.is_absolute():
            raise ReconciliationError(f"{card_id}: declared file must be project-relative")
        path = _inside(root, relative)
        if path.exists():
            declared_records.append(
                _hash_record(
                    path,
                    display=relative.as_posix(),
                    evidence_kind="declared_implementation_file",
                )
            )
    if not declared_records:
        raise ReconciliationError(f"{card_id}: no declared implementation file exists")
    sections = set(map(str, card["affected_sections"]))
    if not sections or not sections <= KNOWN_AFFECTED_SECTIONS:
        raise ReconciliationError(f"{card_id}: affected test-section ownership is invalid")
    if not _nonempty_strings(card["acceptance_criteria"]):
        raise ReconciliationError(f"{card_id}: acceptance criteria are not actionable")
    if not _nonempty_strings(card["focused_tests"]) or not _nonempty_strings(
        card["affected_tests"]
    ):
        raise ReconciliationError(f"{card_id}: focused/affected test ownership is absent")
    return [*records, *declared_records]


def _evidence_reference(record: Mapping[str, object]) -> str:
    reference = f"{record['path']}#sha256={record['sha256']}"
    anchor = record.get("anchor")
    if anchor:
        reference += f"#anchor={anchor}"
    return reference


def _utc_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReconciliationError(f"{label} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ReconciliationError(f"{label} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReconciliationError(f"{label} must be UTC")
    return value


def _verified_artifact(
    root: Path,
    value: object,
    *,
    label: str,
    require_size: bool = False,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label} must be a hash-bound artifact object")
    raw_path = value.get("path")
    expected_sha = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise ReconciliationError(f"{label}.path must be non-empty")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ReconciliationError(f"{label}.sha256 must be lowercase SHA-256")
    path = _inside(root, Path(raw_path))
    if not path.is_file() or path.is_symlink() or _sha256(path) != expected_sha:
        raise ReconciliationError(f"{label} bytes do not match the retained hash")
    if require_size and value.get("size") != path.stat().st_size:
        raise ReconciliationError(f"{label}.size does not match the retained bytes")
    return {
        "path": Path(raw_path).as_posix(),
        "sha256": expected_sha,
        "size": path.stat().st_size,
    }


def _validate_installed_proof(root: Path, relative: Path) -> dict[str, object]:
    path = _inside(root, relative)
    if not path.is_file():
        raise ReconciliationError(f"installed-operational proof is absent: {relative}")
    proof = _load_json(path)
    if proof.get("schema_version") != "px.installed-operational-run-summary/1.1":
        raise ReconciliationError("installed-operational proof has the wrong schema")
    campaign_id = str(proof.get("campaign_id") or "")
    if not re.fullmatch(
        r"pacify-x-certification-\d{8}-final[1-9]\d*-single",
        campaign_id,
    ):
        raise ReconciliationError("installed proof is not bound to a successor candidate")
    claim_id = str(proof.get("claim_id") or "")
    if not claim_id.startswith(
        f"release-stage:{campaign_id}:installed_operational:"
    ):
        raise ReconciliationError("installed proof claim is not bound to its candidate")
    identity_sha = str(proof.get("release_identity_sha256") or "")
    product_digest = str(proof.get("source_product_digest") or "")
    harness_digest = str(proof.get("source_harness_digest") or "")
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (identity_sha, product_digest, harness_digest)
    ):
        raise ReconciliationError("installed proof lacks exact source/release identity")
    if (
        proof.get("all_passed") is not True
        or proof.get("cross_platform_smokes_parallel") is not True
        or proof.get("windows_hosts_serialized") is not True
    ):
        raise ReconciliationError(
            "installed denominator lacks its passing concurrency contract"
        )
    if proof.get("retries") != 0:
        raise ReconciliationError("installed denominator contains a retry")
    finished_utc = _utc_timestamp(proof.get("finished_utc"), label="finished_utc")
    artifact = _verified_artifact(
        root, proof.get("artifact"), label="artifact", require_size=True
    )
    package_evidence = _verified_artifact(
        root, proof.get("package_receipt"), label="package_receipt", require_size=True
    )
    install_evidence = _verified_artifact(
        root, proof.get("install_receipt"), label="install_receipt", require_size=True
    )
    members = proof.get("members")
    if (
        not isinstance(members, list)
        or len(members) != 3
        or {row.get("member") for row in members if isinstance(row, dict)}
        != {
            "windows-exact-vsix-smoke",
            "ubuntu-exact-vsix-smoke",
            "exhaustive-installed-exact-vsix-host-walk",
        }
    ):
        raise ReconciliationError("installed denominator members are not exact")
    if any(not isinstance(row, dict) or row.get("exit_code") != 0 for row in members):
        raise ReconciliationError("an installed-operational member did not pass")
    for row in members:
        member = str(row["member"])
        for field in ("log", "receipt"):
            _verified_artifact(root, row.get(field), label=f"{member}.{field}")
        if row.get("artifact_unchanged") is not True:
            raise ReconciliationError(f"{member} did not retain immutable artifact bytes")
        if row.get("process_tree_closed_verified") is not True:
            raise ReconciliationError(f"{member} process tree did not close")
        if member != "exhaustive-installed-exact-vsix-host-walk":
            _verified_artifact(
                root,
                row.get("process_lifecycle_receipt"),
                label=f"{member}.process_lifecycle_receipt",
            )
    exhaustive = next(
        row for row in members
        if row.get("member") == "exhaustive-installed-exact-vsix-host-walk"
    )
    required = {
        "terminal_state": "completed",
        "operationally_complete": True,
        "scope_complete": True,
        "issue_count": 0,
        "blocking_issue_count": 0,
        "host_error_count": 0,
        "profile_failure_count": 0,
        "process_tree_closed_verified": True,
        "workspace_reclaimed": True,
        "artifact_unchanged": True,
    }
    mismatched = {key: (exhaustive.get(key), value) for key, value in required.items() if exhaustive.get(key) != value}
    if mismatched:
        raise ReconciliationError(f"exhaustive installed proof is incomplete: {mismatched}")
    _verified_artifact(root, exhaustive.get("report"), label="exhaustive.report")
    return {
        "path": relative.as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "schema_version": proof["schema_version"],
        "campaign_id": proof["campaign_id"],
        "claim_id": claim_id,
        "release_identity_sha256": identity_sha,
        "source_product_digest": product_digest,
        "source_harness_digest": harness_digest,
        "artifact": artifact,
        "package_receipt": package_evidence,
        "install_receipt": install_evidence,
        "finished_utc": finished_utc,
    }


def _validate_close_control_plane(
    root: Path,
    installed_evidence: Mapping[str, object],
    automation_state: Path,
    *,
    allow_completed: bool,
) -> None:
    identity_path = root / ".engineering-bootstrap/processing-order/release-identity.json"
    identity = _load_json(identity_path)
    if identity.get("schema_version") != "px.release-campaign/1.0":
        raise ReconciliationError("release identity has the wrong schema")
    if identity.get("campaign_id") != installed_evidence.get("campaign_id"):
        raise ReconciliationError(
            "release identity campaign does not match the installed proof"
        )
    if identity.get("active_claim") is not None:
        raise ReconciliationError("release identity still has an active claim")
    if identity.get("state") != "active" or identity.get("apply_count") != 1:
        raise ReconciliationError("release identity is not the single active candidate")
    kernel = identity.get("identity")
    if not isinstance(kernel, dict):
        raise ReconciliationError("release identity kernel is absent")
    kernel_without_sha = {
        key: value for key, value in kernel.items() if key != "release_identity_sha256"
    }
    if (
        kernel.get("schema_version") != "px.release-identity-kernel/2.0"
        or kernel.get("campaign_id") != identity.get("campaign_id")
        or identity.get("repair_campaign_id")
        != "pacify-x-cohesion-closure-repair12-20260905"
        or kernel.get("repair_campaign_id") != identity.get("repair_campaign_id")
        or kernel.get("release_identity_sha256") != _object_sha256(kernel_without_sha)
        or kernel.get("release_identity_sha256")
        != installed_evidence.get("release_identity_sha256")
        or kernel.get("source_product_digest")
        != installed_evidence.get("source_product_digest")
        or kernel.get("source_harness_digest")
        != installed_evidence.get("source_harness_digest")
    ):
        raise ReconciliationError("release identity kernel does not match installed proof")
    stages = identity.get("stages")
    if not isinstance(stages, dict) or tuple(stages) != RELEASE_STAGES:
        raise ReconciliationError("release identity stage inventory/order is not exact")
    previous_finished: datetime | None = None
    release_windows: dict[str, tuple[datetime, datetime]] = {}
    for stage_name in RELEASE_STAGES[:-1]:
        stage = stages[stage_name]
        claim = stage.get("claim_id") if isinstance(stage, dict) else None
        if (
            not isinstance(stage, dict)
            or stage.get("status") != "passed"
            or not isinstance(claim, str)
            or not claim.startswith(
                f"release-stage:{identity['campaign_id']}:{stage_name}:"
            )
        ):
            raise ReconciliationError(
                f"release identity stage {stage_name} was not passed exactly once"
            )
        claimed = _utc_timestamp(
            stage.get("claimed_at"), label=f"{stage_name}.claimed_at"
        )
        finished = _utc_timestamp(
            stage.get("finished_at"), label=f"{stage_name}.finished_at"
        )
        claimed_at = datetime.fromisoformat(claimed.replace("Z", "+00:00"))
        finished_at = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        if claimed_at > finished_at or (
            previous_finished is not None and claimed_at < previous_finished
        ):
            raise ReconciliationError(f"release identity stage {stage_name} is out of order")
        release_windows[stage_name] = (claimed_at, finished_at)
        previous_finished = finished_at
    if stages["certify"] != {"status": "pending", "claim_id": None}:
        raise ReconciliationError("release identity certify stage is not pending")
    installed = stages.get("installed_operational")
    if not isinstance(installed, dict) or installed.get("status") != "passed":
        raise ReconciliationError("release identity installed_operational is not passed")
    if installed.get("claim_id") != installed_evidence.get("claim_id"):
        raise ReconciliationError(
            "release identity installed_operational claim does not match the proof"
        )
    package_stage = stages.get("package")
    install_stage = stages.get("install")
    if (
        not isinstance(package_stage, dict)
        or package_stage.get("status") != "passed"
        or not isinstance(install_stage, dict)
        or install_stage.get("status") != "passed"
    ):
        raise ReconciliationError("release identity package/install stages are not passed")
    package_claim = str(package_stage.get("claim_id") or "")
    install_claim = str(install_stage.get("claim_id") or "")
    campaign_id = str(identity["campaign_id"])
    if not package_claim.startswith(f"release-stage:{campaign_id}:package:") or not install_claim.startswith(
        f"release-stage:{campaign_id}:install:"
    ):
        raise ReconciliationError("release identity package/install claims are malformed")
    artifact = installed_evidence["artifact"]
    assert isinstance(artifact, dict)
    repair12 = _load_json(root / DEFAULT_EVIDENCE[3])
    repair12_artifact = repair12.get("immutable_artifact")
    if (
        not isinstance(repair12_artifact, dict)
        or repair12_artifact.get("reference") != artifact.get("path")
        or repair12_artifact.get("artifact_sha256") != artifact.get("sha256")
        or repair12_artifact.get("artifact_size") != artifact.get("size")
        or repair12_artifact.get("unchanged") is not True
    ):
        raise ReconciliationError(
            "installed artifact does not match repair12 immutable artifact"
        )
    if artifact.get("path") != (
        f"extension/dist/pacify-x-vscode-{kernel.get('extension_version')}.vsix"
    ):
        raise ReconciliationError("installed artifact does not match the release extension identity")
    package_record = installed_evidence["package_receipt"]
    install_record = installed_evidence["install_receipt"]
    assert isinstance(package_record, dict) and isinstance(install_record, dict)
    package = _load_json(_inside(root, Path(str(package_record["path"]))))
    install_receipt = _load_json(_inside(root, Path(str(install_record["path"]))))
    common_identity = (
        package.get("campaign_id") == identity.get("campaign_id")
        and install_receipt.get("campaign_id") == identity.get("campaign_id")
        and package.get("release_identity_sha256")
        == kernel.get("release_identity_sha256")
        and install_receipt.get("release_identity_sha256")
        == kernel.get("release_identity_sha256")
        and package.get("source_product_digest") == kernel.get("source_product_digest")
        and install_receipt.get("source_product_digest")
        == kernel.get("source_product_digest")
        and package.get("source_harness_digest") == kernel.get("source_harness_digest")
        and install_receipt.get("source_harness_digest")
        == kernel.get("source_harness_digest")
    )
    if not common_identity:
        raise ReconciliationError("package/install evidence identity does not match candidate")
    if (
        package.get("schema_version") != "px.release-stage-evidence/1.0"
        or package.get("stage") != "package"
        or package.get("status") != "passed"
        or package.get("claim_id") != package_stage.get("claim_id")
        or package.get("attempt_count") != 1
        or package.get("artifact") != artifact
        or package.get("artifact_unchanged") is not True
        or package.get("artifact_rebuilt") is not False
        or package.get("artifact_touched") is not False
        or package.get("valid") is not True
    ):
        raise ReconciliationError("package evidence does not bind the installed artifact")
    _require_zero_resources(package, label="candidate package")
    _validate_path_hash_fields(
        root,
        package,
        path_field="audit_log",
        hash_field="audit_log_sha256",
        label="candidate package audit log",
    )
    if (
        install_receipt.get("schema_version") != "px.install-audit-denominator/1.0"
        or install_receipt.get("audit_valid") is not True
        or install_receipt.get("install_claim_id") != install_stage.get("claim_id")
        or install_receipt.get("artifact") != artifact
        or install_receipt.get("tree_digest_before")
        != install_receipt.get("tree_digest_after")
        or install_receipt.get("installed_tree_unchanged") is not True
        or install_receipt.get("release_stage") != "passed"
        or install_receipt.get("processing_phase") != "installed"
        or install_receipt.get("valid") is not True
    ):
        raise ReconciliationError("install evidence does not bind the installed artifact")
    _require_zero_resources(install_receipt, label="candidate install")
    _validate_path_hash_fields(
        root,
        install_receipt,
        path_field="audit_log",
        hash_field="audit_log_sha256",
        label="candidate install audit log",
    )

    automation_path = _inside(root, automation_state)
    if not automation_path.is_file() or automation_path.is_symlink():
        raise ReconciliationError("candidate automation state is not a regular file")
    automation = _load_json(automation_path)
    steps = automation.get("steps")
    expected_steps = (*PRIOR_AUTOMATION_STEPS, "card_reconcile")
    if (
        automation.get("schema_version")
        != "px.release-candidate-automation-state/1.0"
        or automation.get("candidate_id") != identity.get("campaign_id")
        or not isinstance(steps, dict)
        or tuple(steps) != expected_steps
    ):
        raise ReconciliationError("candidate automation stage inventory/order is not exact")
    previous_step_finished: datetime | None = None
    for step_name in PRIOR_AUTOMATION_STEPS:
        step = steps[step_name]
        if (
            not isinstance(step, dict)
            or step.get("status") != "passed"
            or step.get("attempt_count") != 1
            or not str(step.get("gap_id") or "").strip()
            or not str(step.get("admission_event_id") or "").strip()
            or not isinstance(step.get("details"), dict)
            or step["details"].get("valid") is not True
        ):
            raise ReconciliationError(
                f"candidate automation step {step_name} was not passed exactly once"
            )
        started = _utc_timestamp(
            step.get("started_utc"), label=f"{step_name}.started_utc"
        )
        finished = _utc_timestamp(
            step.get("finished_utc"), label=f"{step_name}.finished_utc"
        )
        started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
        finished_at = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        if started_at > finished_at or (
            previous_step_finished is not None and started_at < previous_step_finished
        ):
            raise ReconciliationError(
                f"candidate automation step {step_name} is out of order"
            )
        if step_name in release_windows:
            claimed_at, stage_finished_at = release_windows[step_name]
            if not (
                started_at <= claimed_at <= stage_finished_at <= finished_at
            ):
                raise ReconciliationError(
                    f"candidate automation step {step_name} does not enclose its release stage"
                )
        previous_step_finished = finished_at
    running = steps["card_reconcile"]
    common_running = (
        not isinstance(running, dict)
        or running.get("attempt_count") != 1
        or not str(running.get("gap_id") or "").strip()
        or not str(running.get("admission_event_id") or "").strip()
    )
    if common_running:
        raise ReconciliationError("candidate card_reconcile step is not the sole running owner")
    card_started = _utc_timestamp(
        running.get("started_utc"), label="card_reconcile.started_utc"
    )
    card_started_at = datetime.fromisoformat(card_started.replace("Z", "+00:00"))
    if previous_step_finished is not None and card_started_at < previous_step_finished:
        raise ReconciliationError("candidate card_reconcile step is out of order")
    if allow_completed:
        if (
            running.get("status") != "passed"
            or not isinstance(running.get("details"), dict)
            or running["details"].get("valid") is not True
        ):
            raise ReconciliationError("completed card_reconcile is not passed exactly once")
        card_finished = _utc_timestamp(
            running.get("finished_utc"), label="card_reconcile.finished_utc"
        )
        if card_started_at > datetime.fromisoformat(
            card_finished.replace("Z", "+00:00")
        ):
            raise ReconciliationError("completed card_reconcile is out of order")
    elif (
        running.get("status") != "running"
        or "finished_utc" in running
        or "details" in running
    ):
        raise ReconciliationError("candidate card_reconcile step is not the sole running owner")

    try:
        status = _resource_status(
            root / ".engineering-bootstrap/resource-lifecycle/ledger.json"
        )
    except (OSError, ValueError, TypeError) as error:
        raise ReconciliationError(f"resource status is unreadable: {error}") from error
    required_zero = ("active_processes", "reclaimable_paths", "cleanup_failures")
    nonzero = {key: status.get(key) for key in required_zero if status.get(key) != 0}
    if nonzero:
        raise ReconciliationError(
            f"resource status is not clean for close: {nonzero}"
        )


def _resource_status(ledger_path: Path) -> dict[str, object]:
    from runtime.resource_lifecycle import resource_status

    return resource_status(ledger_path)


def _advance_card(
    card: dict[str, Any],
    *,
    target: str,
    at: str,
    evidence: list[dict[str, object]],
) -> dict[str, Any]:
    updated = json.loads(json.dumps(card))
    current = str(updated["status"])
    if current == "closed" or (current == target):
        return updated
    if target == "downstream_green" and current == "closed":
        return updated
    current_index = LIFECYCLE.index(current)
    target_index = LIFECYCLE.index(target)
    if current_index > target_index:
        return updated
    references = [_evidence_reference(row) for row in evidence]
    history = list(updated.get("status_history", ()))
    for status in LIFECYCLE[current_index + 1 : target_index + 1]:
        history.append(
            {
                "status": status,
                "at": at,
                "evidence": references,
                "reason": "Evidence-backed reconciliation of the frozen 43-card denominator.",
            }
        )
    updated["status"] = target
    updated["status_history"] = history
    updated["completion_evidence"] = list(
        dict.fromkeys([*map(str, updated.get("completion_evidence", ())), *references])
    )
    updated["closure_reconciliation"] = {
        "schema_version": "px.cohesion-card-reconciliation/1.0",
        "target_status": target,
        "reconciled_at": at,
        "acceptance_criteria_count": len(updated["acceptance_criteria"]),
        "evidence": evidence,
    }
    return updated


def _project_dag(
    dag: dict[str, Any], cards: Mapping[str, Mapping[str, object]]
) -> dict[str, Any]:
    updated = json.loads(json.dumps(dag))
    closed_source = sorted(
        card_id for card_id in SOURCE_CARD_IDS if cards[card_id]["status"] == "closed"
    )
    downstream_source = sorted(
        card_id
        for card_id in SOURCE_CARD_IDS
        if cards[card_id]["status"] in {"downstream_green", "closed"}
    )
    remaining = sorted(SOURCE_CARD_IDS - set(downstream_source))
    updated["progress"] = {
        "closed_audit_cards": len(
            [card_id for card_id in AUDIT_CARD_IDS if cards[card_id]["status"] == "closed"]
        ),
        "closed_source_or_proof_cards": len(closed_source),
        "downstream_green_source_or_proof_cards": len(downstream_source),
        "remaining_source_or_proof_cards": len(remaining),
        "active_card": remaining[0] if remaining else None,
        "last_closed_card": closed_source[-1] if closed_source else None,
    }
    return updated


def _current_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ReconciliationError("unable to resolve the current Git HEAD")
    return value


def _project_management_state(
    state: dict[str, Any],
    *,
    target: str,
    head: str,
    evidence: list[dict[str, object]],
) -> dict[str, Any]:
    if state.get("schema_version") != "1.0":
        raise ReconciliationError("project-management state schema is not 1.0")
    for field in ("checkpoint", "knowledge", "lifecycle", "work"):
        if not isinstance(state.get(field), dict):
            raise ReconciliationError(f"project-management state lacks {field}")
    updated = json.loads(json.dumps(state))
    checkpoint = updated["checkpoint"]
    checkpoint["degraded_components"] = []
    checkpoint["failures"] = [
        "final99 is terminal after its one installed-operational denominator; repair12 focused proofs closed all five direct route/projection roots without replay."
    ]
    checkpoint["next_safe_action"] = (
        "Run successor-candidate certification once from the passing installed-operational denominator."
        if target == "closed"
        else "Freeze repair12, reconcile generated projections once, and enter the successor candidate's registered release stages."
    )
    checkpoint["open_circuits"] = (
        ["publication remains closed until successor-candidate certification passes"]
        if target == "closed"
        else ["successor-candidate release stages remain closed until repair12 is frozen"]
    )
    repository = checkpoint.get("repository")
    if not isinstance(repository, dict):
        raise ReconciliationError("project-management checkpoint lacks repository")
    repository["branch"] = "main"
    repository["commit"] = head
    validation = checkpoint.get("validation")
    if not isinstance(validation, dict):
        raise ReconciliationError("project-management checkpoint lacks validation")
    validation["tests"] = (
        "All 37 cohesion source/proof cards are closed against the exact passing successor-candidate installed-operational proof."
        if target == "closed"
        else "All 37 cohesion source/proof cards are evidence-bound and downstream-green; final99 full/validation and repair12 focused owners passed."
    )
    validation["verifier"] = "scripts/reconcile_cohesion_cards.py"
    checkpoint["revision"] = max(int(checkpoint.get("revision", 0)), 44)
    updated["lifecycle"].update(
        {
            "next_action": checkpoint["next_safe_action"],
            "phase": (
                "successor-candidate-certification"
                if target == "closed"
                else "repair12-freeze-and-successor-release"
            ),
            "status": (
                "installed-operational-green-certification-pending"
                if target == "closed"
                else "downstream-green-release-pending"
            ),
        }
    )
    updated["work"]["active_punch_card"] = None
    updated["work"]["cohesion_card_summary"] = {
        "audit_cards_closed": 6,
        "source_or_proof_cards": 37,
        "source_or_proof_downstream_green": 37,
        "source_or_proof_closed": 37 if target == "closed" else 0,
        "remaining": 0,
        "evidence": [
            _evidence_reference(row) for row in evidence
        ],
    }
    updated["knowledge"]["unknowns"] = [
        (
            "Final publication remains contingent on one passing successor-candidate certification and its separately admitted network publication."
            if target == "closed"
            else "Final publication remains contingent on one ordered successor release campaign."
        ),
        "Real macOS installed-host execution remains external-authority evidence and must not be inferred from declarations.",
    ]
    return updated


def _readme(cards: Mapping[str, Mapping[str, object]]) -> str:
    closed = sum(cards[card_id]["status"] == "closed" for card_id in SOURCE_CARD_IDS)
    downstream = sum(
        cards[card_id]["status"] in {"downstream_green", "closed"}
        for card_id in SOURCE_CARD_IDS
    )
    if closed == 37:
        progress = (
            "Current progress: six audit cards and all 37 source/proof cards are "
            "closed. The exact successor-candidate installed-operational proof was accepted; "
            "certification is pending."
        )
    else:
        progress = (
            f"Current progress: six audit cards are closed; {downstream} of 37 "
            f"source/proof cards are downstream-green and {closed} are closed. "
            f"{37 - downstream} source/proof cards remain before release admission."
        )
    return (
        "# Pacify-X cohesion-closure punch cards\n\n"
        "This directory is the durable 43-card implementation contract for the "
        "source-bound cohesion denominator. `dag.json` is the canonical dependency "
        "graph, and `SHA256SUMS` binds the current card projection.\n\n"
        f"{progress}\n\n"
        "Lifecycle: `planned -> admitted -> in_progress -> focused_green -> "
        "downstream_green -> closed`. A source/proof card can become closed only after "
        "the exact successor-candidate installed-operational denominator passes without retry.\n\n"
        "Every completion reference is content-hash-bound. Reconciliation is check-only "
        "unless `scripts/reconcile_cohesion_cards.py --apply` is invoked explicitly.\n"
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def _manifest_bytes(outputs: Mapping[str, bytes]) -> bytes:
    order = ["dag.json", *sorted(name for name in outputs if name.startswith("PX-")), "README.md"]
    return "".join(
        f"{hashlib.sha256(outputs[name]).hexdigest()}  {name}\n" for name in order
    ).encode("utf-8")


def _validate_transaction_set(
    root: Path, transitions: tuple[JsonTransition, ...]
) -> None:
    directory = root / CARD_DIRECTORY
    expected = {
        *(directory / f"{card_id}.json" for card_id in ALL_CARD_IDS),
        directory / "dag.json",
        directory / "README.md",
        directory / "SHA256SUMS",
        root / ".engineering-bootstrap/project-management/state.json",
    }
    by_path = {transition.path: transition.after for transition in transitions}
    if set(by_path) != {path.resolve() for path in expected}:
        raise ReconciliationError("WAL projection target inventory is not exact")
    cards = {
        card_id: by_path[(directory / f"{card_id}.json").resolve()]
        for card_id in ALL_CARD_IDS
    }
    if not all(isinstance(card, dict) for card in cards.values()):
        raise ReconciliationError("WAL card projection is not JSON")
    for card_id, card in cards.items():
        assert isinstance(card, dict)
        _validate_card(card_id, card)
    dag = by_path[(directory / "dag.json").resolve()]
    if not isinstance(dag, dict):
        raise ReconciliationError("WAL DAG projection is not JSON")
    _validate_dag(dag, cards)
    readme = by_path[(directory / "README.md").resolve()]
    manifest = by_path[(directory / "SHA256SUMS").resolve()]
    state = by_path[
        (root / ".engineering-bootstrap/project-management/state.json").resolve()
    ]
    if not isinstance(readme, str) or not isinstance(manifest, str):
        raise ReconciliationError("WAL text projection is not UTF-8 text")
    if not isinstance(state, dict) or state.get("schema_version") != "1.0":
        raise ReconciliationError("WAL project-management state is invalid")
    rendered = {
        **{
            f"{card_id}.json": _json_bytes(cards[card_id])
            for card_id in ALL_CARD_IDS
        },
        "dag.json": _json_bytes(dag),
        "README.md": readme.encode("utf-8"),
    }
    if manifest.encode("utf-8") != _manifest_bytes(rendered):
        raise ReconciliationError("WAL checksum projection does not bind the staged set")


def reconcile(
    root: Path,
    *,
    apply: bool = False,
    target: str = "downstream_green",
    installed_proof: Path | None = None,
    automation_state: Path | None = None,
    at: str | None = None,
    observed_head: str | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    if target not in {"downstream_green", "closed"}:
        raise ReconciliationError(f"unsupported target: {target}")
    directory = _inside(root, CARD_DIRECTORY)
    if not directory.is_dir():
        raise ReconciliationError(f"card directory is absent: {CARD_DIRECTORY}")
    wal = JsonWal(
        root / RECOVERY_JOURNAL,
        root,
        precommit_validator=lambda transitions: _validate_transaction_set(
            root, transitions
        ),
    )
    if apply:
        wal_status = wal.recover()
    else:
        wal_status = wal.inspect()
        if wal_status["requires_recovery"]:
            raise ReconciliationError(
                "cohesion WAL requires recovery; rerun with --apply to recover before reconciliation"
            )
    _parse_checksums(directory)
    cards = {
        card_id: _load_json(directory / f"{card_id}.json")
        for card_id in sorted(ALL_CARD_IDS)
    }
    for card_id, card in cards.items():
        _validate_card(card_id, card)
    card_evidence = {
        card_id: _validate_card_evidence(root, card_id, cards[card_id])
        for card_id in sorted(SOURCE_CARD_IDS)
    }
    dag = _load_json(directory / "dag.json")
    _validate_dag(dag, cards)
    if any(cards[card_id]["status"] != "closed" for card_id in AUDIT_CARD_IDS):
        raise ReconciliationError("all six audit cards must remain closed")

    evidence = _validate_evidence(
        root,
        DEFAULT_EVIDENCE,
        require_final99_identity=target == "downstream_green",
    )
    if target == "closed":
        source_statuses = {str(cards[card_id]["status"]) for card_id in SOURCE_CARD_IDS}
        if source_statuses not in ({"downstream_green"}, {"closed"}):
            raise ReconciliationError(
                "closed requires all 37 cards in one downstream_green or closed projection"
            )
        if installed_proof is None:
            raise ReconciliationError("closed requires --installed-proof from the candidate")
        if automation_state is None:
            raise ReconciliationError("closed requires --automation-state from the candidate")
        installed_evidence = _validate_installed_proof(root, installed_proof)
        _validate_close_control_plane(
            root,
            installed_evidence,
            automation_state,
            allow_completed=source_statuses == {"closed"},
        )
        if source_statuses == {"closed"}:
            for card_id in SOURCE_CARD_IDS:
                closure = cards[card_id].get("closure_reconciliation")
                retained = closure.get("evidence") if isinstance(closure, dict) else None
                if (
                    not isinstance(retained, list)
                    or not any(
                        isinstance(row, dict)
                        and row.get("path") == installed_evidence["path"]
                        and row.get("sha256") == installed_evidence["sha256"]
                        for row in retained
                    )
                ):
                    raise ReconciliationError(
                        f"{card_id}: closed projection is bound to a different proof"
                    )
        evidence.append(installed_evidence)

    if at is not None:
        timestamp = _utc_timestamp(at, label="--at")
    elif target == "closed":
        timestamp = str(evidence[-1]["finished_utc"])
    else:
        repair = _load_json(root / DEFAULT_EVIDENCE[3])
        timestamp = _utc_timestamp(repair.get("observed_utc"), label="repair12 observed_utc")
    projected_cards = {
        card_id: (
            _advance_card(
                cards[card_id],
                target=target,
                at=timestamp,
                evidence=[*evidence, *card_evidence[card_id]],
            )
            if card_id in SOURCE_CARD_IDS
            else cards[card_id]
        )
        for card_id in sorted(cards)
    }
    projected_dag = _project_dag(dag, projected_cards)
    state_path = root / ".engineering-bootstrap/project-management/state.json"
    state = _load_json(state_path)
    head = observed_head or _current_head(root)
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReconciliationError("observed HEAD must be a lowercase 40-character Git hash")
    projected_state = _project_management_state(
        state, target=target, head=head, evidence=evidence
    )
    outputs = {
        **{
            f"{card_id}.json": _json_bytes(projected_cards[card_id])
            for card_id in sorted(ALL_CARD_IDS)
        },
        "dag.json": _json_bytes(projected_dag),
        "README.md": _readme(projected_cards).encode("utf-8"),
    }
    outputs["SHA256SUMS"] = _manifest_bytes(outputs)
    changed = sorted(
        name for name, content in outputs.items()
        if (directory / name).read_bytes() != content
    )
    state_bytes = _json_bytes(projected_state)
    state_changed = state_path.read_bytes() != state_bytes
    changed_source_cards = sorted(
        card_id for card_id in SOURCE_CARD_IDS if f"{card_id}.json" in changed
    )
    report = {
        "schema_version": "px.cohesion-card-reconciliation-plan/1.0",
        "mode": "apply" if apply else "check",
        "valid": True,
        "target_status": target,
        "audit_card_count": 6,
        "source_or_proof_card_count": 37,
        "proposed_card_transition_count": len(changed_source_cards),
        "proposed_card_ids": changed_source_cards,
        "evidence": evidence,
        "projected_progress": projected_dag["progress"],
        "changed_files": [
            *[str((CARD_DIRECTORY / name).as_posix()) for name in changed],
            *([".engineering-bootstrap/project-management/state.json"] if state_changed else []),
        ],
        "changed_file_count": len(changed) + int(state_changed),
        "applied": apply,
        "wal": wal_status,
    }
    if apply and (changed or state_changed):
        artifacts = (
            *(
                JsonTextArtifact(
                    "projection",
                    directory / f"{card_id}.json",
                    outputs[f"{card_id}.json"].decode("utf-8"),
                )
                for card_id in sorted(ALL_CARD_IDS)
            ),
            JsonTextArtifact(
                "projection", directory / "dag.json", outputs["dag.json"].decode("utf-8")
            ),
            TextArtifact(
                "projection", directory / "README.md", outputs["README.md"].decode("utf-8")
            ),
            TextArtifact(
                "projection",
                directory / "SHA256SUMS",
                outputs["SHA256SUMS"].decode("utf-8"),
            ),
            JsonTextArtifact("state", state_path, state_bytes.decode("utf-8")),
        )
        try:
            transaction = wal.commit(artifacts, fault_injector=fault_injector)
        except BaseException:
            wal.recover()
            raise
        report["transaction"] = transaction
        _parse_checksums(directory)
        applied_cards = {
            card_id: _load_json(directory / f"{card_id}.json")
            for card_id in ALL_CARD_IDS
        }
        _validate_dag(_load_json(directory / "dag.json"), applied_cards)
        applied_state = _load_json(state_path)
        if applied_state != projected_state:
            raise ReconciliationError("applied project-management state drifted")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--target", choices=("downstream_green", "closed"), default="downstream_green"
    )
    parser.add_argument("--installed-proof", type=Path)
    parser.add_argument("--automation-state", type=Path)
    parser.add_argument("--at", help="Explicit ISO-8601 reconciliation timestamp")
    parser.add_argument("--observed-head", help="Explicit current 40-character Git HEAD")
    args = parser.parse_args()
    try:
        report = reconcile(
            args.root,
            apply=args.apply,
            target=args.target,
            installed_proof=args.installed_proof,
            automation_state=args.automation_state,
            at=args.at,
            observed_head=args.observed_head,
        )
    except ReconciliationError as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
