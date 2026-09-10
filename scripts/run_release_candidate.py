"""Plan, check, advance one step, or run an ordered PACIFY-X release candidate.

The default mode prints a plan and has no effects. ``--check`` is read-only.
``--execute-next`` journals and runs exactly one next pending owner, then exits.
``--execute-all`` owns the full remaining campaign in one process, creating and
closing a distinct governed work session for every stage and writing one report.
Failed or indeterminate owners are never replayed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Protocol
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CONFIG_SCHEMA = "px.release-candidate-automation/1.0"
STATE_SCHEMA = "px.release-candidate-automation-state/1.0"
STEP_ORDER = (
    "archive_clear",
    "reconcile",
    "identity",
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "card_reconcile",
    "preflight",
    "finalize",
)
PHASE_AFTER = {
    "reconcile": "revision_reconciled",
    "sections": "sections_current",
    "full_profile": "full_profile_passed",
    "validate": "validated",
    "package": "packaged",
    "install": "installed",
    "installed_operational": "installed_operational",
    "finalize": "certified",
}
PHASE_ORDER = (
    "repair_frozen",
    "revision_reconciled",
    "sections_current",
    "full_profile_passed",
    "validated",
    "packaged",
    "installed",
    "installed_operational",
    "certified",
)
RELEASE_STAGE_PHASES = {
    "sections": "revision_reconciled",
    "full_profile": "sections_current",
    "validate": "full_profile_passed",
    "package": "validated",
    "install": "packaged",
    "installed_operational": "installed",
    "certify": "installed_operational",
}
STAGE_AFTER = {
    "sections": "sections",
    "full_profile": "full_profile",
    "validate": "validate",
    "package": "package",
    "install": "install",
    "installed_operational": "installed_operational",
    "preflight": "certify",
    "finalize": "certify",
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DATE_RE = re.compile(r"^20\d{6}$")


class AutomationBlocked(RuntimeError):
    """The candidate cannot advance without risking a replay or phase skip."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise AutomationBlocked(f"state parent is a symlink: {path.parent}")
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.new")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AutomationBlocked(f"expected a JSON object: {path}")
    return value


def _required(value: Mapping[str, Any], key: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result or "\x00" in result:
        raise AutomationBlocked(f"configuration field {key} is required")
    return result


def _inside(root: Path, value: str | Path, key: str) -> Path:
    candidate = Path(value)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AutomationBlocked(f"{key} must remain inside the repository") from exc
    return target


@dataclass(frozen=True)
class Config:
    root: Path
    candidate_id: str
    candidate_date: str
    predecessor_campaign_id: str
    repair_campaign_id: str
    evidence_prefix: str
    artifact: Path
    artifact_sha256: str
    artifact_size: int
    artifact_mtime_ns: int
    automation_state: Path
    log_root: Path
    installed_summary: Path
    installed_exhaustive_receipt: Path
    cohesion_dag: Path
    identity_path_manifest: Path
    timeouts_seconds: Mapping[str, int]
    fresh_paths: tuple[Path, ...]
    owners: Mapping[str, tuple[tuple[str, ...], ...]]

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = _object(path)
        if raw.get("schema_version") != CONFIG_SCHEMA:
            raise AutomationBlocked(f"configuration must use {CONFIG_SCHEMA}")
        root_value = Path(_required(raw, "root"))
        root = (root_value if root_value.is_absolute() else path.parent / root_value).resolve()
        automation_state = _inside(
            root, _required(raw, "automation_state"), "automation_state"
        )
        installed_summary = _inside(
            root, _required(raw, "installed_summary"), "installed_summary"
        )
        installed_exhaustive_receipt = _inside(
            root,
            _required(raw, "installed_exhaustive_receipt"),
            "installed_exhaustive_receipt",
        )
        candidate_id = _required(raw, "candidate_id")
        candidate_date = _required(raw, "candidate_date")
        if not DATE_RE.fullmatch(candidate_date) or candidate_date not in candidate_id:
            raise AutomationBlocked("candidate_date must be YYYYMMDD and occur in candidate_id")
        predecessor = _required(raw, "predecessor_campaign_id")
        if predecessor == candidate_id:
            raise AutomationBlocked("candidate and predecessor IDs must differ")
        digest = _required(raw, "artifact_sha256").lower()
        if not SHA256_RE.fullmatch(digest):
            raise AutomationBlocked("artifact_sha256 is invalid")
        prefix = _required(raw, "evidence_prefix")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", prefix):
            raise AutomationBlocked("evidence_prefix is not path-safe")
        owner_values = raw.get("owners")
        if not isinstance(owner_values, dict) or set(owner_values) != set(STEP_ORDER):
            raise AutomationBlocked("owners must contain every canonical step exactly once")
        owners: dict[str, tuple[tuple[str, ...], ...]] = {}
        for step in STEP_ORDER:
            value = owner_values.get(step)
            commands = value.get("commands") if isinstance(value, dict) else None
            if not isinstance(commands, list) or not commands:
                raise AutomationBlocked(f"owner {step} must define nonempty commands")
            parsed: list[tuple[str, ...]] = []
            for command in commands:
                if (not isinstance(command, list) or not command or any(
                    not isinstance(token, str) or not token or "\x00" in token
                    for token in command
                )):
                    raise AutomationBlocked(f"owner {step} command must be non-shell argv")
                parsed.append(tuple(command))
            if step != "card_reconcile" and len(parsed) != 1:
                raise AutomationBlocked(f"owner {step} must have exactly one command")
            owners[step] = tuple(parsed)
        cards = owners["card_reconcile"]
        if len(cards) != 4:
            raise AutomationBlocked("card_reconcile requires exactly four ordered commands")
        first, second, third, fourth = cards
        if any("python" not in Path(command[0]).name.lower() for command in cards):
            raise AutomationBlocked("card_reconcile commands must use Python")
        installed_relative = installed_summary.relative_to(root).as_posix()
        exhaustive_relative = installed_exhaustive_receipt.relative_to(root).as_posix()
        state_relative = automation_state.relative_to(root).as_posix()
        expected_tails = (
            (
                "-B", "scripts/reconcile_unverified_operational_controls.py",
                "--root", ".", "--check", "--walk-receipt", exhaustive_relative,
                "--reconcile-cards",
            ),
            (
                "-B", "scripts/reconcile_cohesion_cards.py", "--root", ".",
                "--target", "closed", "--installed-proof", installed_relative,
                "--automation-state", state_relative,
            ),
            (
                "-B", "scripts/reconcile_unverified_operational_controls.py",
                "--root", ".", "--walk-receipt", exhaustive_relative,
                "--reconcile-cards",
            ),
            (
                "-B", "scripts/reconcile_cohesion_cards.py", "--root", ".",
                "--target", "closed", "--installed-proof", installed_relative,
                "--automation-state", state_relative, "--apply",
            ),
        )
        if any(command[1:] != expected for command, expected in zip(cards, expected_tails)):
            raise AutomationBlocked(
                "card_reconcile commands differ from the exact installed-proof sequence"
            )
        fresh_values = raw.get("fresh_paths")
        if not isinstance(fresh_values, list) or not fresh_values:
            raise AutomationBlocked("fresh_paths must be a nonempty list")
        fresh_paths = tuple(_inside(root, item, "fresh_paths") for item in fresh_values)
        if len(set(fresh_paths)) != len(fresh_paths):
            raise AutomationBlocked("fresh_paths contains a duplicate")
        timeout_values = raw.get("timeouts_seconds")
        if not isinstance(timeout_values, dict) or set(timeout_values) != set(STEP_ORDER):
            raise AutomationBlocked("timeouts_seconds must bind every canonical step")
        timeouts_seconds = {step: int(timeout_values[step]) for step in STEP_ORDER}
        if any(value <= 0 or value > 7200 for value in timeouts_seconds.values()):
            raise AutomationBlocked("step timeouts must be between 1 and 7200 seconds")
        identity_manifest = raw.get("identity_manifest")
        if not isinstance(identity_manifest, dict):
            raise AutomationBlocked("identity_manifest must be an object")
        identity_path_manifest = _inside(
            root,
            _required(identity_manifest, "path"),
            "identity_manifest.path",
        )
        log_root = _inside(root, _required(raw, "log_root"), "log_root")
        artifact_size = int(raw.get("artifact_size") or 0)
        artifact_mtime_ns = int(raw.get("artifact_mtime_ns") or 0)
        if artifact_size <= 0 or artifact_mtime_ns <= 0:
            raise AutomationBlocked("artifact size and mtime_ns must be positive")
        return cls(
            root=root,
            candidate_id=candidate_id,
            candidate_date=candidate_date,
            predecessor_campaign_id=predecessor,
            repair_campaign_id=_required(raw, "repair_campaign_id"),
            evidence_prefix=prefix,
            artifact=_inside(root, _required(raw, "artifact"), "artifact"),
            artifact_sha256=digest,
            artifact_size=artifact_size,
            artifact_mtime_ns=artifact_mtime_ns,
            automation_state=automation_state,
            log_root=log_root,
            installed_summary=installed_summary,
            installed_exhaustive_receipt=installed_exhaustive_receipt,
            cohesion_dag=_inside(root, _required(raw, "cohesion_dag"), "cohesion_dag"),
            identity_path_manifest=identity_path_manifest,
            timeouts_seconds=timeouts_seconds,
            fresh_paths=fresh_paths,
            owners=owners,
        )

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def plan(config: Config) -> dict[str, Any]:
    return {
        "schema_version": "px.release-candidate-plan/1.0",
        "candidate_id": config.candidate_id,
        "candidate_date": config.candidate_date,
        "default_mode": "plan-only",
        "no_retry": True,
        "steps": [
            {
                "ordinal": index,
                "step": step,
                "owner_commands": [list(command) for command in config.owners[step]],
                "expected_release_stage": STAGE_AFTER.get(step),
                "expected_phase_after": PHASE_AFTER.get(step),
            }
            for index, step in enumerate(STEP_ORDER, 1)
        ],
        "artifact": {
            "path": config.relative(config.artifact),
            "sha256": config.artifact_sha256,
            "size": config.artifact_size,
            "mtime_ns": config.artifact_mtime_ns,
        },
        "outputs": {
            "automation_state": config.relative(config.automation_state),
            "log_root": config.relative(config.log_root),
            "fresh_paths": [config.relative(item) for item in config.fresh_paths],
            "installed_summary": config.relative(config.installed_summary),
            "installed_exhaustive_receipt": config.relative(
                config.installed_exhaustive_receipt
            ),
            "cohesion_dag": config.relative(config.cohesion_dag),
            "identity_path_manifest": config.relative(config.identity_path_manifest),
            "timeouts_seconds": dict(config.timeouts_seconds),
        },
    }


def _release(config: Config) -> dict[str, Any]:
    return _object(
        config.root / ".engineering-bootstrap/processing-order/release-identity.json"
    )


def _repair(config: Config) -> dict[str, Any]:
    return _object(
        config.root / ".engineering-bootstrap/processing-order/repair-campaign.json"
    )


def _invalid_active_predecessor_kind(
    config: Config, release: Mapping[str, Any]
) -> str | None:
    """Classify only structurally valid campaigns invalidated by source drift."""

    if (
        release.get("state") != "active"
        or release.get("apply_count") != 1
        or not isinstance(release.get("identity"), dict)
        or release.get("active_claim") is not None
    ):
        return None
    stages = release.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(RELEASE_STAGE_PHASES):
        return None
    statuses = [
        stages[name].get("status") if isinstance(stages.get(name), dict) else None
        for name in RELEASE_STAGE_PHASES
    ]
    from runtime.release_campaign import release_campaign_status

    structural = release_campaign_status(config.root, verify_source=False)
    source = release_campaign_status(config.root, verify_source=True)
    if (
        structural.get("valid") is not True
        or source.get("valid") is not False
        or not source.get("errors")
    ):
        return None
    if all(status == "pending" for status in statuses):
        return "unused_invalid_identity"
    passed = next(
        (index for index, status in enumerate(statuses) if status != "passed"),
        len(statuses),
    )
    if 0 < passed < len(statuses) and statuses == (
        ["passed"] * passed + ["pending"] * (len(statuses) - passed)
    ):
        return "invalid_active_with_retained_passes"
    return None


def _validate_pre_candidate_hygiene(config: Config) -> None:
    """Require a current certificate-backed hygiene report before a successor."""
    from scripts.pre_candidate_hygiene import validate_report_for_candidate

    validate_report_for_candidate(
        config.root,
        predecessor_campaign_id=config.predecessor_campaign_id,
        artifact=config.artifact,
        artifact_sha256=config.artifact_sha256,
        artifact_size=config.artifact_size,
    )


def readiness(config: Config) -> dict[str, Any]:
    from runtime.release_campaign import cleared_campaign_can_be_superseded

    errors: list[str] = []
    initial = not config.automation_state.exists()
    if not config.root.is_dir():
        errors.append("repository root is missing")
    if not config.artifact.is_file() or config.artifact.is_symlink():
        errors.append("immutable artifact is not an exact non-symlink file")
    else:
        info = config.artifact.stat()
        observed = (_sha256(config.artifact), info.st_size, info.st_mtime_ns)
        expected = (
            config.artifact_sha256,
            config.artifact_size,
            config.artifact_mtime_ns,
        )
        if observed != expected:
            errors.append("immutable artifact identity differs from configuration")
    if initial and any(path.exists() for path in config.fresh_paths):
        errors.append("one or more fresh output paths already exist before the first step")
    if initial:
        repair_phase: str | None = None
        try:
            _validate_pre_candidate_hygiene(config)
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            errors.append(f"pre-candidate hygiene gate failed: {exc}")
        try:
            repair = _repair(config)
            repair_phase = str(repair.get("phase") or "")
            if repair.get("campaign_id") != config.repair_campaign_id:
                errors.append("repair campaign ID differs from configuration")
            if (
                repair_phase not in {"repair_frozen", *RELEASE_STAGE_PHASES.values()}
                or repair.get("intake_open") is not False
                or repair.get("unresolved") != []
            ):
                errors.append("repair campaign is not frozen with an empty denominator")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"repair campaign is unreadable: {type(exc).__name__}")
        try:
            release = _release(config)
            if release.get("campaign_id") != config.predecessor_campaign_id:
                errors.append("predecessor campaign ID differs from configuration")
            predecessor_ready = False
            if release.get("state") == "failed":
                failed_stages = [
                    name
                    for name, record in release.get("stages", {}).items()
                    if isinstance(record, dict) and record.get("status") == "failed"
                ]
                predecessor_ready = (
                    len(failed_stages) == 1
                    and failed_stages[0] in RELEASE_STAGE_PHASES
                    and repair_phase
                    in {
                        "repair_frozen",
                        RELEASE_STAGE_PHASES[failed_stages[0]],
                    }
                )
            elif release.get("state") == "cleared":
                predecessor_ready = (
                    release.get("apply_count") == 0
                    and release.get("identity") is None
                    and repair_phase in {"repair_frozen", "revision_reconciled"}
                    and cleared_campaign_can_be_superseded(release)
                )
            active_kind = _invalid_active_predecessor_kind(config, release)
            if release.get("state") == "active":
                retained_passes = [
                    name
                    for name in RELEASE_STAGE_PHASES
                    if isinstance(release.get("stages", {}).get(name), dict)
                    and release["stages"][name].get("status") == "passed"
                ]
                predecessor_ready = (
                    active_kind == "unused_invalid_identity"
                    and repair_phase in {"repair_frozen", "revision_reconciled"}
                ) or (
                    active_kind == "invalid_active_with_retained_passes"
                    and bool(retained_passes)
                    and repair_phase
                    in {
                        "repair_frozen",
                        RELEASE_STAGE_PHASES[
                            tuple(RELEASE_STAGE_PHASES)[len(retained_passes)]
                        ],
                    }
                )
            if not predecessor_ready or release.get("active_claim") is not None:
                errors.append(
                    "predecessor is not terminal failed, unused cleared, or an "
                    "source-invalid active predecessor"
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"release campaign is unreadable: {type(exc).__name__}")
    else:
        try:
            state = _object(config.automation_state)
            if state.get("schema_version") != STATE_SCHEMA or state.get("candidate_id") != config.candidate_id:
                errors.append("automation state identity is invalid")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"automation state is unreadable: {type(exc).__name__}")
    return {
        "schema_version": "px.release-candidate-readiness/1.0",
        "candidate_id": config.candidate_id,
        "valid": not errors,
        "errors": errors,
    }


class Journal:
    def __init__(self, config: Config):
        self.path = config.automation_state
        if self.path.exists():
            self.value = _object(self.path)
            if (
                self.value.get("schema_version") != STATE_SCHEMA
                or self.value.get("candidate_id") != config.candidate_id
            ):
                raise AutomationBlocked("automation state identity is invalid")
        else:
            self.value = {
                "schema_version": STATE_SCHEMA,
                "candidate_id": config.candidate_id,
                "created_utc": _now(),
                "steps": {},
            }
            _atomic_json(self.path, self.value)

    def status(self, step: str) -> str | None:
        record = self.value["steps"].get(step)
        return str(record.get("status")) if isinstance(record, dict) else None

    def start(self, step: str, *, admission_event_id: str, gap_id: str) -> None:
        if self.status(step) is not None:
            raise AutomationBlocked(f"owner cannot be replayed: {step}")
        self.value["steps"][step] = {
            "status": "running",
            "attempt_count": 1,
            "started_utc": _now(),
            "gap_id": gap_id,
            "admission_event_id": admission_event_id,
        }
        _atomic_json(self.path, self.value)

    def finish(self, step: str, *, passed: bool, details: Mapping[str, Any]) -> None:
        record = self.value["steps"].get(step)
        if not isinstance(record, dict) or record.get("status") != "running":
            raise AutomationBlocked(f"owner has no running attempt: {step}")
        record.update(
            status="passed" if passed else "failed",
            finished_utc=_now(),
            details=dict(details),
        )
        _atomic_json(self.path, self.value)


class OwnerRunner(Protocol):
    def run(
        self, step: str, commands: tuple[tuple[str, ...], ...]
    ) -> Mapping[str, Any]: ...

    def verify(self, step: str) -> None: ...


def _evidence_file(config: Config, value: object, label: str) -> Path:
    if not isinstance(value, dict):
        raise AutomationBlocked(f"{label} must be a path/hash object")
    path = _inside(config.root, _required(value, "path"), label)
    digest = _required(value, "sha256").lower()
    if not path.is_file() or path.is_symlink() or not SHA256_RE.fullmatch(digest):
        raise AutomationBlocked(f"{label} is not an exact evidence file")
    if _sha256(path) != digest:
        raise AutomationBlocked(f"{label} hash differs from the summary")
    return path


def _iso_utc(value: object) -> None:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomationBlocked("installed summary finished_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AutomationBlocked("installed summary finished_utc must be UTC")


def _find_named(value: object, wanted: str) -> list[object]:
    matches: list[object] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if re.sub(r"[^a-z0-9]", "", str(key).lower()) == wanted:
                matches.append(child)
            matches.extend(_find_named(child, wanted))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_find_named(child, wanted))
    return matches


def _derived_count(receipt: object, key: str) -> int:
    values = _find_named(receipt, re.sub(r"[^a-z0-9]", "", key.lower()))
    if not values:
        raise AutomationBlocked(f"exhaustive receipt omits {key}")
    counts = [len(value) if isinstance(value, list) else int(value) for value in values]
    if len(set(counts)) != 1:
        raise AutomationBlocked(f"exhaustive receipt has conflicting {key} values")
    return counts[0]


def _validate_stage_receipt(
    config: Config,
    reference: object,
    *,
    label: str,
    identity: Mapping[str, Any],
    expected_claim_id: str,
) -> dict[str, Any]:
    path = _evidence_file(config, reference, f"{label}_receipt")
    receipt = _object(path)
    expected = {
        "campaign_id": config.candidate_id,
        "release_identity_sha256": identity.get("release_identity_sha256"),
        "source_product_digest": identity.get("source_product_digest"),
        "source_harness_digest": identity.get("source_harness_digest"),
    }
    for key, value in expected.items():
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value) and key != "campaign_id":
            raise AutomationBlocked(f"live release identity {key} is invalid")
        if receipt.get(key) != value:
            raise AutomationBlocked(f"{label} receipt {key} differs from release identity")
    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict):
        raise AutomationBlocked(f"{label} receipt artifact binding is missing")
    if (
        _inside(config.root, _required(artifact, "path"), f"{label}.artifact")
        != config.artifact
        or artifact.get("sha256") != config.artifact_sha256
        or artifact.get("size") != config.artifact_size
    ):
        raise AutomationBlocked(f"{label} receipt artifact differs from the candidate")
    claim = receipt.get("claim_id")
    if label == "install" and claim is None:
        claim = receipt.get("install_claim_id")
    if claim != expected_claim_id:
        raise AutomationBlocked(f"{label} receipt claim differs from the release stage")
    expected_schema = (
        "px.release-stage-evidence/1.0"
        if label == "package"
        else "px.install-audit-denominator/1.0"
    )
    if receipt.get("schema_version") != expected_schema or receipt.get("valid") is not True:
        raise AutomationBlocked(f"{label} receipt is not valid canonical evidence")
    if label == "package":
        exact = {
            "stage": "package",
            "status": "passed",
            "attempt_count": 1,
            "artifact_mtime_ns": config.artifact_mtime_ns,
            "crc_clean": True,
            "unsafe_path_count": 0,
            "encrypted_count": 0,
            "symlink_count": 0,
            "artifact_unchanged": True,
            "artifact_rebuilt": False,
            "artifact_touched": False,
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
        }
        if any(receipt.get(key) != value for key, value in exact.items()):
            raise AutomationBlocked("package receipt contradicts the passed exact audit")
        entry_count = receipt.get("entry_count")
        if (
            not isinstance(entry_count, int)
            or entry_count <= 0
            or receipt.get("unique_entry_count") != entry_count
        ):
            raise AutomationBlocked("package receipt entry denominator is invalid")
    else:
        exact = {
            "install_claim_id": expected_claim_id,
            "exact_version_count": 1,
            "normalized_package_json_entries": 1,
            "missing": [],
            "extra": [],
            "mismatches": [],
            "crc_failures": [],
            "installed_symlinks_before": [],
            "installed_symlinks_after": [],
            "installed_tree_unchanged": True,
            "machine_mutated": False,
            "install_command_executed": False,
            "release_stage": "passed",
            "processing_phase": "installed",
            "resource_count": 0,
            "active_processes": 0,
            "cleanup_failures": 0,
            "audit_valid": True,
        }
        if any(receipt.get(key) != value for key, value in exact.items()):
            raise AutomationBlocked("install receipt contradicts the passed exact audit")
        count = receipt.get("installable_entry_count")
        before = receipt.get("tree_digest_before")
        if (
            not isinstance(count, int)
            or count <= 0
            or receipt.get("installed_file_count") != count
            or receipt.get("verified_byte_identical_entries") != count - 1
            or receipt.get("tree_digest_after") != before
            or not isinstance(before, str)
            or not SHA256_RE.fullmatch(before)
        ):
            raise AutomationBlocked("install receipt denominator is invalid")
    return receipt


def validate_installed_summary(config: Config) -> dict[str, Any]:
    """Validate hash-bound installed evidence before downstream certification."""

    if not config.installed_summary.is_file() or config.installed_summary.is_symlink():
        raise AutomationBlocked("installed operational summary is missing")
    summary = _object(config.installed_summary)
    if summary.get("schema_version") != "px.installed-operational-run-summary/1.1":
        raise AutomationBlocked("installed operational summary schema must be 1.1")
    if summary.get("campaign_id") != config.candidate_id:
        raise AutomationBlocked("installed summary campaign differs from the candidate")
    release = _release(config)
    identity = release.get("identity")
    if not isinstance(identity, dict):
        raise AutomationBlocked("live release identity is missing")
    for key in (
        "release_identity_sha256", "source_product_digest", "source_harness_digest"
    ):
        expected = identity.get(key)
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise AutomationBlocked(f"live release identity {key} is invalid")
        if summary.get(key) != expected:
            raise AutomationBlocked(f"installed summary {key} differs from release identity")
    installed_claim = release.get("stages", {}).get("installed_operational", {}).get("claim_id")
    if (
        not isinstance(installed_claim, str)
        or summary.get("claim_id") != installed_claim
        or not installed_claim.startswith(
            f"release-stage:{config.candidate_id}:installed_operational:"
        )
    ):
        raise AutomationBlocked("installed summary claim is not candidate-bound")
    _iso_utc(summary.get("finished_utc"))
    for key, expected in {
        "all_passed": True,
        "retries": 0,
        "cross_platform_smokes_parallel": True,
        "windows_hosts_serialized": True,
    }.items():
        if summary.get(key) != expected:
            raise AutomationBlocked(f"installed summary {key} is not {expected!r}")
    artifact = summary.get("artifact")
    if not isinstance(artifact, dict):
        raise AutomationBlocked("installed summary artifact is invalid")
    artifact_path = _inside(config.root, _required(artifact, "path"), "artifact")
    if artifact_path != config.artifact or artifact.get("sha256") != config.artifact_sha256:
        raise AutomationBlocked("installed summary artifact identity differs")
    if artifact.get("size") != config.artifact_size:
        raise AutomationBlocked("installed summary artifact size differs")
    observed = config.artifact.stat()
    if (_sha256(config.artifact), observed.st_size, observed.st_mtime_ns) != (
        config.artifact_sha256, config.artifact_size, config.artifact_mtime_ns
    ):
        raise AutomationBlocked("immutable artifact changed during installed proof")
    stages = release.get("stages")
    if not isinstance(stages, dict):
        raise AutomationBlocked("live release stages are missing")
    package_claim = stages.get("package", {}).get("claim_id")
    install_claim = stages.get("install", {}).get("claim_id")
    if not isinstance(package_claim, str) or not isinstance(install_claim, str):
        raise AutomationBlocked("package/install release claims are missing")
    _validate_stage_receipt(
        config, summary.get("package_receipt"), label="package",
        identity=identity, expected_claim_id=package_claim,
    )
    _validate_stage_receipt(
        config, summary.get("install_receipt"), label="install",
        identity=identity, expected_claim_id=install_claim,
    )
    members = summary.get("members")
    expected_names = {
        "windows-exact-vsix-smoke",
        "ubuntu-exact-vsix-smoke",
        "exhaustive-installed-exact-vsix-host-walk",
    }
    if not isinstance(members, list) or len(members) != 3:
        raise AutomationBlocked("installed summary must contain exactly three members")
    by_name = {
        str(item.get("member")): item for item in members if isinstance(item, dict)
    }
    if set(by_name) != expected_names:
        raise AutomationBlocked("installed summary member set is incomplete")
    for name in expected_names:
        member = by_name[name]
        if member.get("exit_code") != 0 or member.get("artifact_unchanged") is not True:
            raise AutomationBlocked(f"installed member is not successful: {name}")
        if member.get("process_tree_closed_verified") is not True:
            raise AutomationBlocked(f"installed member process tree is not closed: {name}")
        _evidence_file(config, member.get("log"), f"{name}.log")
        _evidence_file(config, member.get("receipt"), f"{name}.receipt")
        if name != "exhaustive-installed-exact-vsix-host-walk":
            _evidence_file(
                config, member.get("process_lifecycle_receipt"),
                f"{name}.process_lifecycle_receipt",
            )
    exhaustive = by_name["exhaustive-installed-exact-vsix-host-walk"]
    for key, expected in {
        "terminal_state": "completed",
        "scope_complete": True,
        "operationally_complete": True,
        "issue_count": 0,
        "blocking_issue_count": 0,
        "host_error_count": 0,
        "profile_failure_count": 0,
        "workspace_reclaimed": True,
    }.items():
        if exhaustive.get(key) != expected:
            raise AutomationBlocked(f"exhaustive installed proof {key} is not {expected!r}")
    report_path = _evidence_file(config, exhaustive.get("report"), "exhaustive.report")
    receipt_path = _evidence_file(config, exhaustive.get("receipt"), "exhaustive.receipt")
    report = _object(report_path)
    receipt = _object(receipt_path)
    truth = report.get("status_truth", {})
    status = report.get("child_lifecycle", {}).get("operational_status", {})
    derived = {
        "terminal_state": truth.get("terminal_state"),
        "operationally_complete": truth.get("operationally_complete"),
        "issue_count": truth.get("summary", {}).get("issue_count"),
        "blocking_issue_count": truth.get("summary", {}).get("blocking_issue_count"),
        "scope_complete": status.get("scope_complete"),
        "process_tree_closed_verified": report.get("owner_lifecycle", {}).get(
            "process_tree_closed_verified"
        ),
        "workspace_reclaimed": report.get("cleanup", {}).get("reclaimed"),
        "artifact_unchanged": report.get("child_lifecycle", {}).get(
            "installed_artifact", {}
        ).get("unchanged_after_install"),
    }
    for key, value in derived.items():
        if exhaustive.get(key) != value:
            raise AutomationBlocked(f"exhaustive summary disagrees with report: {key}")
    if exhaustive.get("host_error_count") != _derived_count(receipt, "host_errors"):
        raise AutomationBlocked("exhaustive host error count disagrees with receipt")
    if exhaustive.get("profile_failure_count") != _derived_count(receipt, "profile_failures"):
        raise AutomationBlocked("exhaustive profile failure count disagrees with receipt")
    return summary


def _prepare_identity_manifest(config: Config) -> dict[str, Any]:
    """Freeze the exact Git-visible source and mutable-control path sets."""

    from runtime.release_identity import _release_dirty_state

    if config.identity_path_manifest.exists():
        raise AutomationBlocked(
            f"identity path manifest already exists: {config.identity_path_manifest}"
        )
    dirty = _release_dirty_state(config.root)
    if dirty.get("classifier_errors"):
        raise AutomationBlocked("release source classification is invalid")
    source_paths = sorted(set(dirty.get("blocking_paths", ())), key=str.casefold)
    mutable_paths = sorted(
        set(dirty.get("mutable_control_paths", ())), key=str.casefold
    )
    if set(source_paths) & set(mutable_paths):
        raise AutomationBlocked("identity source and mutable path sets overlap")
    value = {
        "schema_version": "px.release-identity-path-manifest/1.0",
        "candidate_id": config.candidate_id,
        "paths": source_paths,
        "mutable_paths": mutable_paths,
    }
    _atomic_json(config.identity_path_manifest, value)
    return value


class SubprocessOwners:
    def __init__(self, config: Config, manager: Any | None = None):
        self.config = config
        if manager is None:
            from runtime.resource_lifecycle import ResourceManager

            manager = ResourceManager(
                config.root / ".engineering-bootstrap/resource-lifecycle/ledger.json",
                receipt_dir=config.root
                / ".engineering-bootstrap/resource-lifecycle/cleanup-receipts",
            )
        self.manager = manager

    def run(
        self, step: str, commands: tuple[tuple[str, ...], ...]
    ) -> Mapping[str, Any]:
        self.config.log_root.mkdir(parents=True, exist_ok=True)
        if step == "identity":
            _prepare_identity_manifest(self.config)
        environment = dict(os.environ)
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(self.config.root))
        evidence: list[dict[str, Any]] = []
        valid = True
        timeout_seconds = self.config.timeouts_seconds[step]
        deadline = time.monotonic() + timeout_seconds
        for index, argv in enumerate(commands, 1):
            suffix = "" if len(commands) == 1 else f"-{index:02d}"
            log = self.config.log_root / f"{self.config.evidence_prefix}-{step}{suffix}.log"
            if log.exists():
                raise AutomationBlocked(f"owner log already exists: {log}")
            started = time.monotonic()
            with log.open("x", encoding="utf-8", newline="\n") as stream:
                record, process = self.manager.spawn_owned_process(
                    list(argv),
                    cwd=self.config.root,
                    project_id="pacify-x",
                    run_id=self.config.candidate_id,
                    lane_id=f"{step}-{index:02d}",
                    creator="scripts.run_release_candidate",
                    ownership="supervised",
                    environment={
                        **environment,
                        "PX_RELEASE_OWNER_RUN_ID": self.config.candidate_id,
                        "PX_RELEASE_OWNER_LANE_ID": f"{step}-{index:02d}",
                    },
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                remaining = max(0.0, deadline - time.monotonic())
                cleanup: dict[str, Any] | None = None
                owner_closed = False
                try:
                    returncode = process.wait(timeout=remaining)
                    completed_record = self.manager.complete_process(record.resource_id)
                    owner_closed = True
                    from runtime.resource_lifecycle import resource_status

                    post_resources = resource_status(
                        self.config.root
                        / ".engineering-bootstrap/resource-lifecycle/ledger.json"
                    )
                    if any(
                        post_resources.get(field) != 0
                        for field in (
                            "active_processes",
                            "active_paths",
                            "reclaimable_paths",
                            "cleanup_failures",
                        )
                    ):
                        raise AutomationBlocked(
                            f"owner resources did not close after exit: {step}"
                        )
                    lifecycle = {
                        "status": completed_record.status,
                        "run_state": completed_record.run_state,
                        "cleanup_result": completed_record.cleanup_result,
                        "process_tree_closed_verified": True,
                        "resource_status_after_exit": post_resources,
                    }
                except subprocess.TimeoutExpired as exc:
                    try:
                        receipt = self.manager.terminate_owned_process(record.resource_id)
                    except BaseException:
                        self.manager.settle_failed_launch(record.resource_id, exc)
                        raise AutomationBlocked(
                            f"owner exceeded its bounded deadline and cleanup remains unresolved: {step}; resource={record.resource_id}"
                        ) from exc
                    cleanup = {
                        "cleanup_id": receipt.cleanup_id,
                        "resources_reclaimed": receipt.resources_reclaimed,
                        "resources_failed": receipt.resources_failed,
                        "errors": list(receipt.errors),
                    }
                    if receipt.resources_failed or receipt.errors:
                        raise AutomationBlocked(
                            f"owner timeout cleanup did not close its process tree: {step}; resource={record.resource_id}; cleanup={receipt.cleanup_id}"
                        ) from exc
                    raise AutomationBlocked(
                        f"owner exceeded its {timeout_seconds}s bounded deadline: {step}; resource={record.resource_id}; cleanup={receipt.cleanup_id}"
                    ) from exc
                except BaseException as error:
                    if not owner_closed:
                        self.manager.settle_failed_launch(record.resource_id, error)
                    raise
            evidence.append({
                "exit_code": returncode,
                "log": self.config.relative(log),
                "log_sha256": _sha256(log),
                "resource_id": record.resource_id,
                "pid": record.pid,
                "timeout_seconds": timeout_seconds,
                "duration_seconds": round(time.monotonic() - started, 3),
                "lifecycle": lifecycle,
                "timeout_cleanup": cleanup,
            })
            if returncode != 0:
                valid = False
                break
        details = {
            "valid": valid,
            "commands": evidence,
        }
        if valid:
            self.verify(step)
        return details

    def verify(self, step: str) -> None:
        if step in {"installed_operational", "card_reconcile", "preflight", "finalize"}:
            validate_installed_summary(self.config)
        release = _release(self.config)
        repair = _repair(self.config)
        phase = repair.get("phase")

        def phase_at_least(expected: str) -> bool:
            return (
                phase in PHASE_ORDER
                and PHASE_ORDER.index(str(phase)) >= PHASE_ORDER.index(expected)
            )

        if step == "archive_clear":
            valid = (
                release.get("campaign_id") == self.config.candidate_id
                and (
                    (
                        release.get("state") == "cleared"
                        and
                        release.get("apply_count") == 0
                        and release.get("active_claim") is None
                        and all(
                            row.get("status") == "pending"
                            for row in release.get("stages", {}).values()
                            if isinstance(row, dict)
                        )
                    )
                    or (
                        release.get("state") in {"active", "certified"}
                        and release.get("apply_count") == 1
                    )
                )
            )
        elif step == "reconcile":
            valid = (
                release.get("campaign_id") == self.config.candidate_id
                and release.get("state") in {"cleared", "active", "certified"}
                and phase_at_least("revision_reconciled")
            )
        elif step == "identity":
            valid = (
                release.get("campaign_id") == self.config.candidate_id
                and release.get("state") in {"active", "certified"}
                and release.get("apply_count") == 1
                and isinstance(release.get("identity"), dict)
            )
        elif step == "card_reconcile":
            from scripts.reconcile_unverified_operational_controls import (
                operational_reconciliation_status,
            )

            dag = _object(self.config.cohesion_dag)
            progress = dag.get("progress", {})
            operational = operational_reconciliation_status(
                self.config.root, self.config.installed_exhaustive_receipt
            )
            valid = (
                release.get("campaign_id") == self.config.candidate_id
                and release.get("state") in {"active", "certified"}
                and phase_at_least("installed_operational")
                and release.get("stages", {}).get("installed_operational", {}).get("status")
                == "passed"
                and progress.get("closed_source_or_proof_cards") == 37
                and progress.get("remaining_source_or_proof_cards") == 0
                and operational.get("valid") is True
            )
        elif step == "preflight":
            claim = release.get("active_claim")
            certify_status = release.get("stages", {}).get("certify", {}).get("status")
            valid = (
                certify_status == "passed"
                or (
                    certify_status == "claimed"
                    and isinstance(claim, dict)
                    and claim.get("stage") == "certify"
                )
            )
        else:
            stage = STAGE_AFTER[step]
            valid = release.get("stages", {}).get(stage, {}).get("status") == "passed"
            if step in PHASE_AFTER:
                valid = valid and phase_at_least(PHASE_AFTER[step])
            if step == "finalize":
                valid = valid and release.get("state") == "certified"
        if not valid:
            raise AutomationBlocked(f"owner exited zero without its postcondition: {step}")


def next_pending_step(config: Config, owners: OwnerRunner) -> str | None:
    """Return the sole step that may run, verifying all earlier postconditions."""

    if not config.automation_state.exists():
        return STEP_ORDER[0]
    value = _object(config.automation_state)
    if value.get("schema_version") != STATE_SCHEMA or value.get("candidate_id") != config.candidate_id:
        raise AutomationBlocked("automation state identity is invalid")
    steps = value.get("steps")
    if not isinstance(steps, dict):
        raise AutomationBlocked("automation state steps are invalid")
    for step in STEP_ORDER:
        record = steps.get(step)
        status = record.get("status") if isinstance(record, dict) else None
        if status == "passed":
            owners.verify(step)
            continue
        if status is not None:
            raise AutomationBlocked(
                f"owner {step} is {status}; no retry is allowed for this candidate"
            )
        later = STEP_ORDER[STEP_ORDER.index(step) + 1 :]
        if any(name in steps for name in later):
            raise AutomationBlocked("automation journal skips canonical order")
        return step
    return None


def execute_next(
    config: Config, owners: OwnerRunner, *, admission_event_id: str, gap_id: str
) -> dict[str, Any]:
    step = next_pending_step(config, owners)
    if step is None:
        raise AutomationBlocked("candidate already has every step passed")
    journal = Journal(config)
    journal.start(step, admission_event_id=admission_event_id, gap_id=gap_id)
    try:
        details = dict(owners.run(step, config.owners[step]))
        details.update(
            admission_event_id=admission_event_id,
            gap_id=gap_id,
            executed_step=step,
        )
        passed = details.get("valid") is True
    except Exception as exc:
        journal.finish(step, passed=False, details={
            "error": f"{type(exc).__name__}: {exc}",
            "admission_event_id": admission_event_id,
            "gap_id": gap_id,
            "executed_step": step,
        })
        raise
    journal.finish(step, passed=passed, details=details)
    if not passed:
        raise AutomationBlocked(f"owner failed and cannot be retried: {step}")
    return {
        "schema_version": "px.release-candidate-step-result/1.0",
        "candidate_id": config.candidate_id,
        "executed_step": step,
        "next_step": next_pending_step(config, owners),
        "admission_event_id": admission_event_id,
        "valid": True,
    }


class LedgerCampaignGovernance:
    """Open, close, and checkpoint one exact ledger session per campaign step."""

    def __init__(self, config: Config, gap_id: str):
        self.config = config
        self.gap_id = gap_id

    def _snapshot(self) -> dict[str, Any]:
        from runtime.operational_gap_ledger import read_snapshot

        return read_snapshot(self.config.root)

    def admit(self, step: str) -> dict[str, str]:
        from runtime.operational_gap_ledger import append_event

        snapshot = self._snapshot()
        checkpoint = snapshot.get("work_checkpoints", [])[-1]
        if checkpoint.get("active_gap_id") != self.gap_id:
            raise AutomationBlocked("campaign gap differs from the active checkpoint")
        session_id = (
            f"release-campaign:{self.config.evidence_prefix}:{step}:{uuid4().hex[:12]}"
        )
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=self.config.timeouts_seconds[step] + 3600
        )
        event = append_event(
            self.config.root,
            "work_admitted",
            {
                "gap_id": self.gap_id,
                "checkpoint_event_id": checkpoint["event_id"],
                "session_id": session_id,
                "authority": (
                    f"Run the {self.config.candidate_id} {step} owner exactly once "
                    "inside the registered release campaign order."
                ),
                "effect_scopes": [
                    {
                        "effect": "read",
                        "scope": [
                            "Exact candidate configuration, predecessor state, artifact, stage evidence, and lifecycle resources."
                        ],
                    },
                    {
                        "effect": "write",
                        "scope": [
                            "Only the current candidate stage state, registered evidence/logs, governed projections, and this work-session ledger trail."
                        ],
                    },
                    {
                        "effect": "execute",
                        "scope": [
                            f"Exactly one registered {step} owner under its {self.config.timeouts_seconds[step]}-second deadline."
                        ],
                    },
                ],
                "expected_effect": (
                    f"The {step} owner reaches its exact postcondition once and the "
                    "campaign advances only to the next registered stage."
                ),
                "rollback": (
                    "On failure retain terminal evidence, close owned resources, stop "
                    "the campaign, and do not replay the failed owner."
                ),
                "expires_utc": expires.isoformat().replace("+00:00", "Z"),
                "evidence": [{
                    "reference": self.config.relative(self.config.artifact),
                    "artifact_sha256": self.config.artifact_sha256,
                    "artifact_size": self.config.artifact_size,
                    "claim": (
                        f"The campaign admission is bound to the exact immutable "
                        f"{self.config.candidate_id} VSIX bytes."
                    ),
                }],
            },
            actor="codex-primary:release-campaign-runner",
        )
        return {
            "event_id": str(event["event_id"]),
            "session_id": session_id,
            "checkpoint_event_id": str(checkpoint["event_id"]),
        }

    def _state_evidence(self, step: str) -> list[dict[str, Any]]:
        if not self.config.automation_state.is_file():
            return []
        return [{
            "reference": self.config.relative(self.config.automation_state),
            "artifact_sha256": _sha256(self.config.automation_state),
            "artifact_size": self.config.automation_state.stat().st_size,
            "claim": f"The append-only candidate journal records the sole {step} terminal result.",
        }]

    def settle(self, step: str, admission: Mapping[str, str], *, passed: bool) -> dict[str, str]:
        from runtime.operational_gap_ledger import append_event

        evidence = self._state_evidence(step)
        closure = append_event(
            self.config.root,
            "work_session_closed",
            {
                "gap_id": self.gap_id,
                "session_id": admission["session_id"],
                "admission_event_id": admission["event_id"],
                "outcome": "completed" if passed else "cancelled",
                "reason": (
                    f"{self.config.candidate_id} {step} passed its exact postcondition once."
                    if passed else
                    f"{self.config.candidate_id} {step} terminated without a passing postcondition; downstream stages were not run."
                ),
                "evidence": evidence,
            },
            actor="codex-primary:release-campaign-runner",
        )
        snapshot = self._snapshot()
        prior = snapshot.get("work_checkpoints", [])[-1]
        cards = snapshot.get("cards", {})
        card = cards.get(self.gap_id, {})
        prior_sequence = int(prior.get("sequence") or 0)
        newly = sorted(
            gap_id for gap_id, value in cards.items()
            if int(value.get("discovery_sequence") or 0) > prior_sequence
        )
        unresolved = sorted(
            gap_id for gap_id in newly
            if gap_id != self.gap_id
            and cards[gap_id].get("current_state") not in {"closed", "superseded"}
        )
        checkpoint = append_event(
            self.config.root,
            "work_checkpoint",
            {
                "active_gap_id": self.gap_id,
                "previous_checkpoint_event_id": prior["event_id"],
                "learned": (
                    f"{self.config.candidate_id} {step} passed exactly once; the campaign runner will continue in registered order."
                    if passed else
                    f"{self.config.candidate_id} {step} failed once; the candidate is terminal and downstream stages remain unexecuted."
                ),
                "next_action": card.get("next_action"),
                "newly_discovered_gap_ids": newly,
                "unresolved_branch_gap_ids": unresolved,
                "evidence": evidence,
            },
            actor="codex-primary:release-campaign-runner",
        )
        return {
            "closure_event_id": str(closure["event_id"]),
            "checkpoint_event_id": str(checkpoint["event_id"]),
        }


def execute_all(
    config: Config,
    owners: OwnerRunner,
    *,
    gap_id: str,
    report_path: Path,
    governance: Any | None = None,
) -> dict[str, Any]:
    """Run every remaining owner once and retain one aggregate campaign report."""

    report_path = _inside(config.root, report_path, "campaign_report")
    if report_path.exists():
        raise AutomationBlocked(f"campaign report already exists: {report_path}")
    governance = governance or LedgerCampaignGovernance(config, gap_id)
    started = _now()
    stages: list[dict[str, Any]] = []
    failure: str | None = None
    while True:
        step = next_pending_step(config, owners)
        if step is None:
            break
        print(json.dumps({"campaign_progress": "started", "step": step}), flush=True)
        step_started = time.monotonic()
        try:
            admission = governance.admit(step)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            stages.append({
                "step": step,
                "passed": False,
                "duration_seconds": round(time.monotonic() - step_started, 3),
                "admission_event_id": None,
                "closure_event_id": None,
                "checkpoint_event_id": None,
                "outcome": None,
                "error": failure,
            })
            partial = {
                "schema_version": "px.release-candidate-campaign-report/1.0",
                "candidate_id": config.candidate_id,
                "started_utc": started,
                "finished_utc": _now(),
                "valid": False,
                "completed_stage_count": 0,
                "stage_count": len(STEP_ORDER),
                "stages": stages,
                "failure": failure,
            }
            _atomic_json(report_path, partial)
            print(json.dumps({
                "campaign_progress": "failed",
                "step": step,
                "report": config.relative(report_path),
            }), flush=True)
            return partial
        passed = False
        outcome: dict[str, Any] | None = None
        try:
            outcome = execute_next(
                config,
                owners,
                admission_event_id=admission["event_id"],
                gap_id=gap_id,
            )
            passed = outcome.get("valid") is True
        except Exception as exc:  # retain the single terminal failure in the report
            failure = f"{type(exc).__name__}: {exc}"
        settlement = governance.settle(step, admission, passed=passed)
        stages.append({
            "step": step,
            "passed": passed,
            "duration_seconds": round(time.monotonic() - step_started, 3),
            "admission_event_id": admission["event_id"],
            **settlement,
            "outcome": outcome,
            "error": failure,
        })
        partial = {
            "schema_version": "px.release-candidate-campaign-report/1.0",
            "candidate_id": config.candidate_id,
            "started_utc": started,
            "finished_utc": _now() if failure else None,
            "valid": failure is None and len(stages) == len(STEP_ORDER),
            "completed_stage_count": sum(1 for item in stages if item["passed"]),
            "stage_count": len(STEP_ORDER),
            "stages": stages,
            "failure": failure,
        }
        _atomic_json(report_path, partial)
        print(json.dumps({"campaign_progress": "passed" if passed else "failed", "step": step, "report": config.relative(report_path)}), flush=True)
        if failure or not passed:
            return partial
    result = {
        "schema_version": "px.release-candidate-campaign-report/1.0",
        "candidate_id": config.candidate_id,
        "started_utc": started,
        "finished_utc": _now(),
        "valid": len(stages) == len(STEP_ORDER),
        "completed_stage_count": len(stages),
        "stage_count": len(STEP_ORDER),
        "stages": stages,
        "failure": None,
    }
    _atomic_json(report_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--execute-next", action="store_true")
    mode.add_argument("--execute-all", action="store_true")
    result.add_argument("--confirm-candidate")
    result.add_argument("--gap-id")
    result.add_argument("--admission-event-id")
    result.add_argument("--campaign-report", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config.resolve(strict=True))
        if not args.check and not args.execute_next and not args.execute_all:
            print(json.dumps(plan(config), indent=2))
            return 0
        if args.check:
            report = readiness(config)
            if report["valid"]:
                report["next_step"] = next_pending_step(config, SubprocessOwners(config))
            print(json.dumps(report, indent=2))
            return 0 if report["valid"] else 1
        if args.confirm_candidate != config.candidate_id:
            raise AutomationBlocked(
                "execution requires --confirm-candidate equal to candidate_id"
            )
        if not str(args.gap_id or "").strip():
            raise AutomationBlocked("execution requires --gap-id")
        if args.execute_all:
            if args.admission_event_id:
                raise AutomationBlocked("--execute-all creates its own per-stage admissions")
            if args.campaign_report is None:
                raise AutomationBlocked("--execute-all requires --campaign-report")
            report = readiness(config)
            if report["valid"] is not True:
                print(json.dumps(report, indent=2))
                return 1
            outcome = execute_all(
                config,
                SubprocessOwners(config),
                gap_id=args.gap_id,
                report_path=args.campaign_report,
            )
            print(json.dumps(outcome, indent=2))
            return 0 if outcome["valid"] else 1
        if not str(args.admission_event_id or "").strip():
            raise AutomationBlocked("--execute-next requires --gap-id and --admission-event-id")
        report = readiness(config)
        if report["valid"] is not True:
            print(json.dumps(report, indent=2))
            return 1
        outcome = execute_next(
            config, SubprocessOwners(config), gap_id=args.gap_id,
            admission_event_id=args.admission_event_id,
        )
        print(json.dumps(outcome, indent=2))
        return 0
    except (AutomationBlocked, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"]},
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
